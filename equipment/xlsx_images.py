"""
Pictures placed *in* cells ("Place in Cell" in Excel 365 / 2021+).

A picture floating over the sheet stays where it is when rows are sorted,
filtered or inserted, so it ends up beside the wrong asset. A picture in a
cell is the cell's value and moves with its row. openpyxl cannot write one,
so the workbook is saved first and the picture parts are added to the file
afterwards, laid out the way Excel (and XlsxWriter's embed_image) writes them.

Usage: ``put_in_cell(sheet, "A5", jpeg_bytes)`` while building, then
``save_workbook(workbook, target)`` instead of ``workbook.save(target)``.
"""

import re
import zipfile
from io import BytesIO

ATTR = "_ema_cell_images"      # {(sheet, "A5"): jpeg bytes}, kept on the workbook

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_RD = "http://schemas.microsoft.com/office/spreadsheetml/2017/richdata"
NS_RD2 = "http://schemas.microsoft.com/office/spreadsheetml/2017/richdata2"
NS_RVREL = "http://schemas.microsoft.com/office/spreadsheetml/2022/richvaluerel"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'

PARTS = [  # (part, content type, workbook relationship type)
    ("metadata.xml", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheetMetadata+xml",
     "http://schemas.openxmlformats.org/officeDocument/2006/relationships/sheetMetadata"),
    ("richData/richValueRel.xml", "application/vnd.ms-excel.richvaluerel+xml",
     "http://schemas.microsoft.com/office/2022/10/relationships/richValueRel"),
    ("richData/rdrichvalue.xml", "application/vnd.ms-excel.rdrichvalue+xml",
     "http://schemas.microsoft.com/office/2017/06/relationships/rdRichValue"),
    ("richData/rdrichvaluestructure.xml", "application/vnd.ms-excel.rdrichvaluestructure+xml",
     "http://schemas.microsoft.com/office/2017/06/relationships/rdRichValueStructure"),
    ("richData/rdRichValueTypes.xml", "application/vnd.ms-excel.rdrichvaluetypes+xml",
     "http://schemas.microsoft.com/office/2017/06/relationships/rdRichValueTypes"),
]

VALUE_TYPES = (
    f'<rvTypesInfo xmlns="{NS_RD2}" xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
    f'mc:Ignorable="x" xmlns:x="{NS_MAIN}"><global><keyFlags>'
    '<key name="_Self"><flag name="ExcludeFromFile" value="1"/><flag name="ExcludeFromCalcComparison" value="1"/></key>'
    + "".join(
        f'<key name="{name}"><flag name="ExcludeFromCalcComparison" value="1"/></key>'
        for name in ("_DisplayString", "_Flags", "_Format", "_SubLabel", "_Attribution", "_Icon",
                     "_Display", "_CanonicalPropertyNames", "_ClassificationId")
    )
    + "</keyFlags></global></rvTypesInfo>"
)


def put_in_cell(sheet, cell_ref: str, jpeg: bytes) -> None:
    """Mark a JPEG to be placed in this cell when the workbook is saved."""
    workbook = sheet.parent
    if not hasattr(workbook, ATTR):
        setattr(workbook, ATTR, {})
    # The sheet itself, not its title: a sheet may be renamed after this.
    getattr(workbook, ATTR)[(sheet, cell_ref)] = jpeg
    # The cell must exist in the saved sheet for the picture to be hung on it.
    cell = sheet[cell_ref]
    if not cell.has_style:
        cell.style = "Normal"


def cell_images(workbook) -> dict:
    """{(sheet title, cell): jpeg} of the pictures waiting to be placed."""
    return {(sheet.title, ref): jpeg for (sheet, ref), jpeg in getattr(workbook, ATTR, {}).items()}


def save_workbook(workbook, target) -> None:
    """Save like workbook.save(target), with any in-cell pictures added."""
    images = cell_images(workbook)
    if not images:
        workbook.save(target)
        return
    plain = BytesIO()
    workbook.save(plain)
    data = _add_pictures(plain.getvalue(), workbook, images)
    if hasattr(target, "write"):
        target.write(data)
    else:
        with open(target, "wb") as fh:
            fh.write(data)


def _add_pictures(xlsx: bytes, workbook, images: dict) -> bytes:
    source = zipfile.ZipFile(BytesIO(xlsx))
    files = {name: source.read(name) for name in source.namelist()}

    # One rich value per picture; vm="n" on a cell points at the n-th (1-based).
    sheet_paths = _sheet_paths(files)
    by_sheet: dict[str, dict[str, int]] = {}
    pictures = []
    for (title, ref), jpeg in images.items():
        pictures.append(jpeg)
        by_sheet.setdefault(title, {})[ref] = len(pictures)

    for title, refs in by_sheet.items():
        path = sheet_paths[title]
        files[path] = _mark_cells(files[path].decode("utf-8"), refs).encode("utf-8")

    count = len(pictures)
    for index, jpeg in enumerate(pictures, start=1):
        files[f"xl/media/cellimage{index}.jpeg"] = jpeg
    files["xl/richData/_rels/richValueRel.xml.rels"] = (
        HEAD + f'<Relationships xmlns="{NS_PKG}">'
        + "".join(
            f'<Relationship Id="rId{i}" Type="{NS_R}/image" Target="../media/cellimage{i}.jpeg"/>'
            for i in range(1, count + 1)
        )
        + "</Relationships>"
    ).encode("utf-8")
    files["xl/richData/richValueRel.xml"] = (
        HEAD + f'<richValueRels xmlns="{NS_RVREL}" xmlns:r="{NS_R}">'
        + "".join(f'<rel r:id="rId{i}"/>' for i in range(1, count + 1))
        + "</richValueRels>"
    ).encode("utf-8")
    files["xl/richData/rdrichvalue.xml"] = (
        HEAD + f'<rvData xmlns="{NS_RD}" count="{count}">'
        + "".join(f'<rv s="0"><v>{i}</v><v>5</v></rv>' for i in range(count))
        + "</rvData>"
    ).encode("utf-8")
    files["xl/richData/rdrichvaluestructure.xml"] = (
        HEAD + f'<rvStructures xmlns="{NS_RD}" count="1"><s t="_localImage">'
        '<k n="_rvRel:LocalImageIdentifier" t="i"/><k n="CalcOrigin" t="i"/></s></rvStructures>'
    ).encode("utf-8")
    files["xl/richData/rdRichValueTypes.xml"] = (HEAD + VALUE_TYPES).encode("utf-8")
    files["xl/metadata.xml"] = (
        HEAD + f'<metadata xmlns="{NS_MAIN}" xmlns:xlrd="{NS_RD}"><metadataTypes count="1">'
        '<metadataType name="XLRICHVALUE" minSupportedVersion="120000" copy="1" pasteAll="1" pasteValues="1" '
        'merge="1" splitFirst="1" rowColShift="1" clearFormats="1" clearComments="1" assign="1" coerce="1"/>'
        f'</metadataTypes><futureMetadata name="XLRICHVALUE" count="{count}">'
        + "".join(
            '<bk><extLst><ext uri="{3e2802c4-a4d2-4d8b-9148-e3be6c30e623}">'
            f'<xlrd:rvb i="{i}"/></ext></extLst></bk>'
            for i in range(count)
        )
        + f'</futureMetadata><valueMetadata count="{count}">'
        + "".join(f'<bk><rc t="1" v="{i}"/></bk>' for i in range(count))
        + "</valueMetadata></metadata>"
    ).encode("utf-8")

    # Register the new parts with the package and the workbook.
    types = files["[Content_Types].xml"].decode("utf-8")
    extra = "" if 'Extension="jpeg"' in types else '<Default Extension="jpeg" ContentType="image/jpeg"/>'
    extra += "".join(f'<Override PartName="/xl/{part}" ContentType="{kind}"/>' for part, kind, _ in PARTS)
    files["[Content_Types].xml"] = types.replace("</Types>", extra + "</Types>").encode("utf-8")

    rels = files["xl/_rels/workbook.xml.rels"].decode("utf-8")
    taken = {int(n) for n in re.findall(r'Id="rId(\d+)"', rels)}
    start = max(taken, default=0) + 1
    extra = "".join(
        f'<Relationship Id="rId{start + i}" Type="{rel}" Target="{part}"/>'
        for i, (part, _, rel) in enumerate(PARTS)
    )
    files["xl/_rels/workbook.xml.rels"] = rels.replace("</Relationships>", extra + "</Relationships>").encode("utf-8")

    out = BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        # [Content_Types].xml first, as Office writes it.
        for name in sorted(files, key=lambda n: n != "[Content_Types].xml"):
            target.writestr(name, files[name])
    return out.getvalue()


def _sheet_paths(files) -> dict[str, str]:
    """Sheet title -> its part inside the package."""
    workbook = files["xl/workbook.xml"].decode("utf-8")
    rels = files["xl/_rels/workbook.xml.rels"].decode("utf-8")
    targets = {}
    for rel in re.findall(r"<Relationship\b[^>]*>", rels):
        rid = re.search(r'Id="([^"]+)"', rel).group(1)
        target = re.search(r'Target="([^"]+)"', rel).group(1)
        targets[rid] = target.lstrip("/") if target.startswith("/") else "xl/" + target
    paths = {}
    for sheet in re.findall(r"<sheet\b[^>]*>", workbook):
        name = re.search(r'name="([^"]+)"', sheet).group(1)
        rid = re.search(r'r:id="([^"]+)"', sheet).group(1)
        paths[_unescape(name)] = targets[rid]
    return paths


def _unescape(text: str) -> str:
    return text.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'").replace("&amp;", "&")


def _mark_cells(xml: str, refs: dict[str, int]) -> str:
    """Turn each listed cell into a picture cell: an error value with vm="n"."""

    def replace(match):
        attrs = match.group(2)
        number = refs.get(match.group(1))
        if number is None:
            return match.group(0)
        attrs = re.sub(r'\s(t|vm)="[^"]*"', "", attrs)
        return f'<c r="{match.group(1)}"{attrs} t="e" vm="{number}"><v>#VALUE!</v></c>'

    return re.sub(r'<c r="([A-Z]+\d+)"((?:\s[^>]*?)?)\s*(?:/>|>.*?</c>)', replace, xml, flags=re.S)
