"""Pictures of equipment for the spreadsheet export (see register.py)."""

from io import BytesIO

from PIL import Image as PILImage

# Size, in pixels, of the photo dropped into each export row's first cell.
PHOTO_CELL_PX = 64


def photo_jpeg(attachment, size: int = PHOTO_CELL_PX):
    """``attachment``'s thumbnail as JPEG bytes no larger than ``size`` pixels, or None."""
    if attachment is None or not attachment.thumbnail:
        return None
    try:
        with attachment.thumbnail.open("rb") as fh:
            raw = fh.read()
    except (FileNotFoundError, OSError):
        return None  # the file record exists but the file is missing on disk
    try:
        with PILImage.open(BytesIO(raw)) as source:
            small = source.convert("RGB")
            small.thumbnail((size, size))
            buffer = BytesIO()
            small.save(buffer, format="JPEG", quality=85)
    except OSError:
        return None  # not a readable image
    return buffer.getvalue()


