"""
Bring the Computime (DataFill) asset register into this app.

Reads what the crawler put in ``data/import/computime/`` — assets.json plus the
downloaded photos — and creates or updates one asset per ZT code.

It prints what it would do and changes nothing unless ``--commit`` is given, so
the register can be inspected before it touches the database.

    manage.py import_computime                 # show what would happen
    manage.py import_computime --commit        # write it
    manage.py import_computime --commit --photos

Only Test Engineering's assets are taken (``--department TE``, the default);
the register also lists ME, QC, PE and IE, which do not belong here. The
location is left empty — their "Department" column is not a place — and only
the plant (CTV1/CTV2) is kept.
"""

import json
import pathlib
import re
from datetime import datetime

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from calibration.models import CalibrationPlan
from core.models import Category, Plant
from core.photos import save_photo
from equipment.models import Equipment, EquipmentStatus

DEFAULT_SOURCE = pathlib.Path(settings.BASE_DIR) / "data" / "import" / "computime"

# Their status vocabulary is shorter than ours.
STATUS = {
    # In service there means "in use somewhere"; In production here means
    # fitted to a running product, which the Products page decides.
    "in service": EquipmentStatus.AVAILABLE,
    "scrapped": EquipmentStatus.RETIRED,
    "missing": EquipmentStatus.DOWN,
    "output of service": EquipmentStatus.AVAILABLE,
    "being sold": EquipmentStatus.RETIRED,
    "end-of-life (eol)": EquipmentStatus.RETIRED,
}

# Categories whose assets are instruments that get calibrated.
MEASURING = {
    "digital multimeter", "measuring tool", "osciliscope", "oscilloscope",
    "temperature measurement",
}

# Three identifiers. The equipment ID is the internal code (CTV20200077),
# found in their "Equipment No." column when someone typed it there; without
# one the ZT code (70-...) stands in until it is filled in by hand. The asset
# number (103220100359) is finance's; their "Asset No" column also holds
# serial numbers typed into the wrong box, so only this form is taken.
EQUIPMENT_ID = re.compile(r"CTV\d{6,}", re.IGNORECASE)
ASSET_NO = re.compile(r"\d{12}")


def equipment_id_for(row: dict) -> str:
    internal = (row.get("equipment_no") or "").strip().upper()
    return internal if EQUIPMENT_ID.fullmatch(internal) else (row.get("zt_code") or "").strip()


def asset_no_for(row: dict) -> str:
    asset_no = (row.get("asset_no") or "").strip()
    return asset_no if ASSET_NO.fullmatch(asset_no) else ""


# What the maintenance interval field offers, in days.
INTERVAL_DAYS = {1: 30, 3: 90, 6: 180, 12: 365, 24: 365}


def parse_date(text: str):
    """'26/Mar/2025' -> date. Their pages use no other format."""
    text = (text or "").strip()
    if not text:
        return None
    for pattern in ("%d/%b/%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def parse_months(text: str) -> int | None:
    """'12 Months' / '12 Month(s)' -> 12."""
    match = re.search(r"(\d+)\s*month", (text or ""), re.IGNORECASE)
    return int(match.group(1)) if match else None


def catalog_code(name: str, used: set[str]) -> str:
    code = slugify(name).upper()[:30] or "MISC"
    candidate, n = code, 2
    while candidate in used:
        candidate = f"{code[:27]}-{n}"
        n += 1
    used.add(candidate)
    return candidate


class Command(BaseCommand):
    help = "Import the crawled Computime asset register (dry run unless --commit)."

    def add_arguments(self, parser):
        parser.add_argument("--source", default=str(DEFAULT_SOURCE),
                            help="Folder holding assets.json and images/.")
        parser.add_argument("--commit", action="store_true",
                            help="Write to the database. Without it, nothing changes.")
        parser.add_argument("--photos", action="store_true",
                            help="Also attach the downloaded photos.")
        parser.add_argument("--limit", type=int, default=0,
                            help="Only the first N assets — for a quick look.")
        parser.add_argument("--department", default="TE",
                            help="Only this department's assets (default TE). 'all' takes every one.")

    def handle(self, *args, **options):
        source = pathlib.Path(options["source"])
        data_file = source / "assets.json"
        if not data_file.exists():
            raise CommandError(f"{data_file} not found — run the crawler first.")
        assets = json.loads(data_file.read_text(encoding="utf-8"))
        department = options["department"].strip().upper()
        if department != "ALL":
            before = len(assets)
            assets = [a for a in assets if (a.get("department") or "").strip().upper() == department]
            self.stdout.write(f"Department {department}: {len(assets)} of {before} assets")
        if options["limit"]:
            assets = assets[: options["limit"]]

        self.commit = options["commit"]
        self.counts = {"created": 0, "updated": 0, "photos": 0, "calibration": 0, "skipped": 0}
        self.category_cache: dict[str, Category] = {}
        self.used_codes = set(Category.objects.values_list("code", flat=True))

        with transaction.atomic():
            for row in assets:
                self.import_one(row, source, options["photos"])
            if not options["commit"]:
                transaction.set_rollback(True)   # everything above is undone

        mode = "WROTE" if options["commit"] else "DRY RUN — nothing was saved"
        self.stdout.write(self.style.SUCCESS(
            f"{mode}: {self.counts['created']} created, {self.counts['updated']} updated, "
            f"{self.counts['photos']} photos, {self.counts['calibration']} calibration plans, "
            f"{self.counts['skipped']} skipped"
        ))

    # --- one asset ---------------------------------------------------------

    def import_one(self, row: dict, source: pathlib.Path, with_photos: bool) -> None:
        zt_code = (row.get("zt_code") or "").strip()
        code = equipment_id_for(row)
        asset_no = asset_no_for(row)
        if not code:
            self.counts["skipped"] += 1
            return

        category = self.category_for(row.get("category") or "Uncategorised")
        plant = self.plant_in(row.get("manufacturer"))
        months = parse_months(row.get("pm_interval") or row.get("pm_frequency") or "")

        fields = {
            "name": (row.get("name") or row.get("description") or code)[:200],
            "asset_no": asset_no,
            "category": category,
            # Where it stands is filled in by hand later; the plant is known.
            "plant": plant,
            # Their "Manufacturer" column holds the plant (CTV1/CTV2), which
            # belongs in the plant field instead — so only keep a real maker.
            "manufacturer": "" if self.is_plant(row.get("manufacturer")) else (row.get("manufacturer") or "")[:150],
            "model_number": (row.get("model") or "")[:150],
            "serial_number": (row.get("serial_no") or "")[:150],
            "status": STATUS.get((row.get("status") or "").strip().lower(), EquipmentStatus.AVAILABLE),
            "is_measuring_device": (row.get("category") or "").strip().lower() in MEASURING,
            "maintenance_required": bool(months),
            "maintenance_interval_days": INTERVAL_DAYS.get(months or 0, 365) if months else None,
            "notes": self.notes_for(row),
        }

        # Found by its asset code, or by the ZT code it was first imported under.
        asset = (
            Equipment.objects.filter(code=code).first()
            or Equipment.objects.filter(notes__contains=f"Computime ZT code: {zt_code}").first()
            or Equipment.objects.filter(code=zt_code).first()
            or (Equipment.objects.filter(asset_no=asset_no).first() if asset_no else None)
        )
        if asset:
            # Never overwrite an ID typed in by hand with a placeholder.
            if code != zt_code or asset.code == zt_code:
                fields["code"] = code
            for key, value in fields.items():
                setattr(asset, key, value)
            asset.save()
            self.counts["updated"] += 1
        else:
            asset = Equipment.objects.create(code=code, **fields)
            self.counts["created"] += 1

        asset.sync_maintenance_plan()
        self.calibration_for(asset, row)
        # Photos are files on disk, which no rollback would remove.
        if with_photos and self.commit:
            self.photos_for(asset, row, source)

    # --- pieces ------------------------------------------------------------

    @staticmethod
    def plant_in(value: str | None) -> str:
        """'CTV2' or 'CTV2 WH' (their warehouse) -> 'CTV2'; anything else -> ''."""
        first = (value or "").strip().upper().split(" ")[0]
        return first if first in Plant.values else ""

    @classmethod
    def is_plant(cls, value: str | None) -> bool:
        return bool(cls.plant_in(value))

    def category_for(self, name: str) -> Category:
        key = name.strip().lower()
        if key not in self.category_cache:
            existing = Category.objects.filter(name__iexact=name.strip()).first()
            if existing is None:
                existing = Category.objects.create(
                    code=catalog_code(name, self.used_codes), name=name.strip()[:150]
                )
            self.category_cache[key] = existing
        return self.category_cache[key]

    @staticmethod
    def notes_for(row: dict) -> str:
        """Everything the app has no field for, kept so nothing is lost."""
        lines = [
            ("Computime ZT code", row.get("zt_code")),
            ("Computime asset no", row.get("asset_no")),
            ("Department", row.get("department")),
            ("Line", row.get("line")),
            ("Equipment no", row.get("equipment_no")),
            ("Condition", row.get("condition")),
            ("Warranty", row.get("warranty")),
            ("Next renewal", row.get("next_renew")),
            ("Last audit", row.get("last_audit")),
            ("Requestor", row.get("requestor")),
            ("Registered by", f"{row.get('registered_by') or ''} {row.get('registered_at') or ''}".strip()),
            ("Source", row.get("source_url")),
        ]
        return "\n".join(f"{label}: {value}" for label, value in lines if (value or "").strip())

    def calibration_for(self, asset: Equipment, row: dict) -> None:
        due = parse_date(row.get("next_calibration"))
        if not (asset.is_measuring_device and due):
            return
        plan, created = CalibrationPlan.objects.get_or_create(
            equipment=asset,
            name="Calibration",
            defaults={"interval_months": 12, "next_due_at": due, "is_active": True},
        )
        if not created and plan.next_due_at != due:
            plan.next_due_at = due
            plan.save(update_fields=["next_due_at", "updated_at"])
        self.counts["calibration"] += 1

    def photos_for(self, asset: Equipment, row: dict, source: pathlib.Path) -> None:
        if asset.attachments.filter(kind="PHOTO").exists():
            return                      # already has photos; leave them alone
        for relative in row.get("photos", []):
            path = source / relative
            if not path.exists():
                continue
            upload = ContentFile(path.read_bytes(), name=path.name)
            try:
                save_photo(asset, upload, None)
                self.counts["photos"] += 1
            except Exception as error:      # a broken file must not stop the run
                self.stderr.write(f"{asset.code}: {path.name} — {error}")
