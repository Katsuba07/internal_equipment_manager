"""
Product documents kept on SharePoint, seen through OneDrive.

The TE folder on SharePoint is synced to this server by OneDrive
(``EMA_DOCS_ROOT``). The app never keeps its own copy:

* ``sync_documents`` walks the synced folder and brings the list of documents
  up to date — new files appear, changed ones are updated, deleted ones go.
  It only reads names, sizes and dates, so OneDrive does not have to download
  anything (files can stay "online only").
* ``store_upload`` writes a file added in the app into the right product and
  type folder; OneDrive carries it to SharePoint, where version history keeps
  whatever it replaced.
* Links open the file on SharePoint itself, so SharePoint's permissions apply.

Folder layout on the share: ``<product folder>/<type folder>/<file>``, where a
product folder can name several products (``KMCB111-121-141``).
"""

import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from urllib.parse import quote

from django.conf import settings
from django.core.cache import cache
from django.db import transaction

from core.models import Customer, Product

from .models import DocumentSection, ProductDocument

# Folder names on the share -> document type. Spelling on the share varies.
SECTIONS = {
    "ti": DocumentSection.TI,
    "test spec": DocumentSection.TEST_SPEC,
    "testing specification": DocumentSection.TEST_SPEC,
    "test specification": DocumentSection.TEST_SPEC,
    "schematic": DocumentSection.SCHEMATIC,
    "bom": DocumentSection.BOM,
    "firmware": DocumentSection.FIRMWARE,
    "firmware update": DocumentSection.FIRMWARE,
    "pcba drawing": DocumentSection.PCBA_DRAWING,
}
# Where a file added in the app goes, when the product has no such folder yet.
SECTION_FOLDERS = {
    DocumentSection.TI: "TI",
    DocumentSection.TEST_SPEC: "Test Spec",
    DocumentSection.SCHEMATIC: "Schematic",
    DocumentSection.BOM: "BOM",
    DocumentSection.FIRMWARE: "Firmware",
    DocumentSection.PCBA_DRAWING: "PCBA Drawing",
    DocumentSection.OTHER: "",
}
# Model code prefix -> customer code.
CUSTOMERS = {"BAF": "BAF", "RMM": "RHEEM", "BRNA": "BRNA", "KMC": "KRAIN"}
# OneDrive's own bookkeeping and Office's lock files are not documents.
IGNORED = re.compile(r"^(desktop\.ini|thumbs\.db|~\$.*|\..*)$", re.IGNORECASE)
LAST_SYNC_KEY = "ema:docs:last-sync"


# ------------------------------------------------------------------ naming


def product_codes(folder: str) -> list[str]:
    """
    'KMCB111-121-141' -> KMCB111, KMCB121, KMCB141
    'BAF7350-BAF7450' -> BAF7350, BAF7450
    'RMMT001'         -> RMMT001
    """
    parts = [p.strip().upper() for p in folder.split("-") if p.strip()]
    if not parts:
        return []
    first = parts[0]
    stem = re.match(r"^([A-Z]+)", first)
    codes = [first]
    for part in parts[1:]:
        codes.append(stem.group(1) + part if part.isdigit() and stem else part)
    return codes


def section_for(folder_parts: list[str]) -> str:
    for part in folder_parts[1:]:
        found = SECTIONS.get(part.strip().lower())
        if found:
            return found
    return DocumentSection.OTHER


def customer_for(code: str):
    for prefix, customer_code in CUSTOMERS.items():
        if code.startswith(prefix):
            return Customer.objects.filter(code=customer_code).first()
    return None


def products_for(folder_parts: list[str]) -> list[Product]:
    products = []
    for code in product_codes(folder_parts[0]) if folder_parts else []:
        product = Product.objects.filter(code=code).first()
        if product is None:
            product = Product.objects.create(
                code=code, customer=customer_for(code), plant=settings.EMA_DOCS_DEFAULT_PLANT,
            )
        products.append(product)
    return products


# ------------------------------------------------------------------ SharePoint links


def _site_path() -> str:
    """'/sites/CTV' out of '/sites/CTV/Shared Documents/...'."""
    return "/".join(settings.EMA_DOCS_SHAREPOINT_FOLDER.split("/")[:3])


def open_url(doc: ProductDocument) -> str:
    """Open on SharePoint: PDFs and Office files show in the browser."""
    return f"{settings.EMA_DOCS_SHAREPOINT_SITE}{quote(doc.source)}?web=1"


def download_url(doc: ProductDocument) -> str:
    return (f"{settings.EMA_DOCS_SHAREPOINT_SITE}{_site_path()}/_layouts/15/download.aspx"
            f"?SourceUrl={quote(doc.source, safe='')}")


def folder_url(relative_folder: str = "") -> str:
    path = settings.EMA_DOCS_SHAREPOINT_FOLDER + ("/" + relative_folder if relative_folder else "")
    return f"{settings.EMA_DOCS_SHAREPOINT_SITE}{quote(path)}"


# ------------------------------------------------------------------ sync


@dataclass
class SyncResult:
    created: int = 0
    updated: int = 0
    removed: int = 0
    unchanged: int = 0
    errors: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return (f"{self.created} new, {self.updated} changed, {self.removed} gone, "
                f"{self.unchanged} unchanged" + (f", {len(self.errors)} problems" if self.errors else ""))


def docs_root() -> Path | None:
    root = settings.EMA_DOCS_ROOT
    return root if root and Path(root).is_dir() else None


def _walk(root: Path):
    """(relative posix path, size, modified) for every document under root."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if IGNORED.match(name):
                continue
            full = Path(dirpath) / name
            try:
                info = full.stat()          # metadata only: an online-only file stays online
            except OSError:
                continue
            relative = full.relative_to(root).as_posix()
            modified = datetime.fromtimestamp(int(info.st_mtime), tz=dt_timezone.utc)
            yield relative, info.st_size, modified


def _record(relative: str, size: int, modified, existing: dict, result: SyncResult):
    parts = relative.split("/")
    folder_parts, name = parts[:-1], parts[-1]
    source = f"{settings.EMA_DOCS_SHAREPOINT_FOLDER}/{relative}"
    doc = existing.pop(source, None)
    if doc is not None and doc.size_bytes == size and doc.source_modified == modified:
        result.unchanged += 1
        return doc
    fresh = doc is None
    doc = doc or ProductDocument(source=source)
    doc.file_name = name
    doc.folder = "/".join(folder_parts)
    doc.section = section_for(folder_parts)
    doc.size_bytes = size
    doc.source_modified = modified
    doc.save()
    doc.products.set(products_for(folder_parts))
    if fresh:
        result.created += 1
    else:
        result.updated += 1
    return doc


@transaction.atomic
def sync_documents() -> SyncResult | None:
    """Bring the list in line with the synced folder. None when there is no folder."""
    root = docs_root()
    if root is None:
        return None
    result = SyncResult()
    prefix = settings.EMA_DOCS_SHAREPOINT_FOLDER + "/"
    existing = {d.source: d for d in ProductDocument.objects.filter(source__startswith=prefix)}

    # Every product folder is a product, even one with no papers yet.
    for entry in os.scandir(root):
        if entry.is_dir() and not entry.name.startswith("."):
            products_for([entry.name])

    for relative, size, modified in _walk(root):
        try:
            _record(relative, size, modified, existing, result)
        except Exception as error:          # one odd file must not stop the rest
            result.errors.append(f"{relative}: {error}")
    for gone in existing.values():          # no longer on SharePoint
        gone.delete()
        result.removed += 1
    cache.set(LAST_SYNC_KEY, time.time(), None)
    return result


def maybe_sync() -> None:
    """Re-read the folder when the list was last read long enough ago."""
    last = cache.get(LAST_SYNC_KEY) or 0
    if time.time() - last >= settings.EMA_DOCS_RESCAN_SECONDS:
        sync_documents()


def last_synced() -> datetime | None:
    stamp = cache.get(LAST_SYNC_KEY)
    return datetime.fromtimestamp(stamp, tz=dt_timezone.utc) if stamp else None


# ------------------------------------------------------------------ adding files


def folder_for(product: Product, section: str) -> str:
    """Where a new file of this product and type belongs, relative to the TE folder."""
    known = product.documents.exclude(folder="").values_list("folder", flat=True).first()
    product_folder = known.split("/")[0] if known else product.code
    root = docs_root()
    wanted = SECTION_FOLDERS.get(section, "")
    if root is not None and section != DocumentSection.OTHER and (root / product_folder).is_dir():
        # Reuse the spelling already on the share ("Testing Specification").
        for entry in os.scandir(root / product_folder):
            if entry.is_dir() and SECTIONS.get(entry.name.strip().lower()) == section:
                wanted = entry.name
                break
    return f"{product_folder}/{wanted}" if wanted else product_folder


def store_upload(product: Product, section: str, upload, user=None) -> ProductDocument:
    """Write the file into the synced folder (replacing one of the same name) and list it."""
    root = docs_root()
    if root is None:
        raise RuntimeError("The SharePoint folder is not synced to this server yet.")
    relative_folder = folder_for(product, section)
    name = Path(upload.name).name
    target = root / relative_folder / name
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as handle:
        for chunk in upload.chunks():
            handle.write(chunk)
    info = target.stat()
    result = SyncResult()
    source = f"{settings.EMA_DOCS_SHAREPOINT_FOLDER}/{relative_folder}/{name}"
    existing = {d.source: d for d in ProductDocument.objects.filter(source=source)}
    doc = _record(f"{relative_folder}/{name}", info.st_size,
                  datetime.fromtimestamp(int(info.st_mtime), tz=dt_timezone.utc), existing, result)
    if user is not None and getattr(user, "is_authenticated", False):
        doc.uploaded_by = user
        doc.save(update_fields=["uploaded_by", "updated_at"])
    return doc
