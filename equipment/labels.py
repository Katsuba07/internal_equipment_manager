"""
Asset labels on the Zebra label printer.

The label is written in ZPL, the printer's own language, and sent to it as-is.
A browser print goes through the Windows driver, which scales the page to
whatever stock it believes is loaded; ZPL places every line in printer dots, so
the label comes out the size it was drawn.
"""

import socket
from dataclasses import dataclass

from django.conf import settings

# The scalable font (^A0) is a condensed bold: a character is roughly half as
# wide as it is tall — capitals and digits, which is most of a label, a
# little more.
CHAR_WIDTH = 0.62
NARROWEST = 0.6          # how far a long value may be squeezed before it is cut
LINE = 3                 # frame thickness, in dots
MARGIN_MM = 1.0          # blank edge around the frame: top, bottom and left
MARGIN_RIGHT_MM = 2.0    # a little more on the right, where the print ran close to the edge


class LabelPrintError(Exception):
    """The label could not be handed to the printer; the message is for the user."""


@dataclass(frozen=True)
class LabelSize:
    """One label, and how the labels sit on the roll. Millimetres."""

    w: float
    h: float
    cols: int = 1
    gap: float = 0.0
    dx: float = 0.0      # nudge the print right (+) or left (-)
    dy: float = 0.0      # nudge the print down (+) or up (-)
    font: float = 0.0    # height of the four lines' text; 0 picks one to suit the label

    LIMITS = {"w": (20, 200), "h": (10, 200), "cols": (1, 4), "gap": (0, 20), "dx": (-20, 20), "dy": (-20, 20), "font": (1, 8)}

    @classmethod
    def from_values(cls, values) -> "LabelSize":
        """Read a size from a form post, falling back to the configured stock."""
        size = dict(settings.EMA_LABEL_SIZE)
        for name, (low, high) in cls.LIMITS.items():
            try:
                number = float(values.get(name, ""))
            except (TypeError, ValueError):
                continue
            if low <= number <= high:
                size[name] = number
        size["cols"] = int(size["cols"])
        return cls(**{name: size.get(name, 0) for name in cls.LIMITS})


def _field(text) -> str:
    """Text for a ^FH\\^FD field: ZPL's own control characters go in as hex."""
    text = " ".join(str(text or "").split())
    return "".join(f"\\{ord(c):02X}" if c in "\\^~" else c for c in text)


def _fitted(text, height, room) -> tuple[str, int]:
    """Squeeze a value into its space, then cut it: (text, character width in dots)."""
    text = " ".join(str(text or "").split())
    if not text:
        return "", height
    width = height
    needed = len(text) * height * CHAR_WIDTH
    if needed > room:
        width = max(int(height * room / needed), int(height * NARROWEST))
        text = text[: max(int(room / (width * CHAR_WIDTH)), 1)]
    return text, width


def _fitted_smaller(text, height, room) -> tuple[str, int, int]:
    """
    Like _fitted, but a value too long even squeezed gets a smaller font (down
    to 60 %) before anything is cut: (text, font height, character width).
    """
    text = " ".join(str(text or "").split())
    if text and len(text) * height * CHAR_WIDTH * NARROWEST > room:
        height = max(int(room / (len(text) * CHAR_WIDTH * NARROWEST)), int(height * 0.6))
    fitted, width = _fitted(text, height, room)
    return fitted, height, width


def _qr_graphic(data: str, room: int) -> tuple[str, int]:
    """
    The QR code as a ZPL graphic, as large as fits in `room` dots: (field, side).

    Drawn here rather than by the printer's own ^BQ so that its size is known
    exactly — it has to sit inside a box only a couple of text rows tall.
    """
    import qrcode

    code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L, border=0)
    code.add_data(data)
    code.make(fit=True)
    matrix = code.get_matrix()
    scale = max(1, room // len(matrix))
    side = len(matrix) * scale
    row_bytes = (side + 7) // 8
    lines = []
    for row in matrix:
        bits = "".join(("1" if cell else "0") * scale for cell in row).ljust(row_bytes * 8, "0")
        lines.extend([f"{int(bits, 2):0{row_bytes * 2}X}"] * scale)
    total = row_bytes * side
    return f"^GFA,{total},{total},{row_bytes},{''.join(lines)}", side


def _name_lines(text, font, room):
    """
    The asset name for its row: one line, squeezed if needed; when even
    squeezed it is too long, two lines in a smaller font, cut to fit.
    Returns (text, font height, font width, lines).
    """
    text = " ".join(str(text or "").split())
    if len(text) * font * CHAR_WIDTH * NARROWEST <= room:
        fitted, width = _fitted(text, font, room)
        return fitted, font, width, 1
    small = int(font * 0.78)
    width = int(small * 0.85)
    per_line = max(int(room / (width * CHAR_WIDTH)), 1)
    return text[: per_line * 2], small, width, 2


def build_zpl(assets, size: LabelSize) -> str:
    """
    The ZPL for labels on the roll, ``size.cols`` labels across.

    One asset fills every label across the row (a single label printed with
    spares); a list of assets fills the labels in order, a new row each time
    the roll is full across.

    Company name across the top, the four lines beneath it, and the QR code
    boxed into the bottom right corner beside the last two lines.
    """
    if not isinstance(assets, (list, tuple)):
        rows_of_assets = [[assets] * size.cols]
    else:
        rows_of_assets = [list(assets[i:i + size.cols]) for i in range(0, len(assets), size.cols)]

    dots = settings.EMA_LABEL_DPI / 25.4

    def d(mm) -> int:
        return int(round(mm * dots))

    inset = d(MARGIN_MM)
    width, height = d(size.w) - inset - d(MARGIN_RIGHT_MM), d(size.h) - 2 * inset
    head = int(height * 0.18)
    row_height = (height - head) // 4
    qr_box = min(2 * row_height, width // 3)
    font = min(d(size.font or min(size.h * 0.1, size.w * 0.055)), row_height - 4)
    pad = d(1)
    caption_width = int(len("EQ Name:") * font * CHAR_WIDTH) + pad
    quiet = 4                                    # blank dots kept around the QR code
    total = d(size.w * size.cols + size.gap * (size.cols - 1))

    out = []
    for row_assets in rows_of_assets:
        out += ["^XA", "^CI28", f"^PW{total}", f"^LL{d(size.h)}", "^LH0,0"]
        for column, equipment in enumerate(row_assets):
            x = max(d(column * (size.w + size.gap) + size.dx) + inset, 0)
            y = max(d(size.dy) + inset, 0)
            box_x, box_y = x + width - qr_box, y + height - qr_box
            qr, qr_side = _qr_graphic(equipment.label_qr_url, qr_box - LINE - 2 * quiet)

            out.append(f"^FO{x},{y}^GB{width},{height},{LINE}^FS")
            out.append(f"^FO{x},{y + head}^GB{width},{LINE},{LINE}^FS")
            out.append(f"^FO{box_x},{box_y}^GB{qr_box},{qr_box},{LINE}^FS")
            offset = (qr_box - qr_side) // 2
            out.append(f"^FO{box_x + offset},{box_y + offset}{qr}^FS")

            text_x = x + LINE + pad
            company_height = min(int(font * 1.1), head - 4)
            company, company_width = _fitted(settings.EMA_LABEL_COMPANY, company_height, width - 2 * (LINE + pad))
            out.append(
                f"^FO{text_x},{y + (head - company_height) // 2 + LINE}"
                f"^A0N,{company_height},{company_width}^FH\\^FD{_field(company)}^FS"
            )
            rows = [
                ("EQ No:", equipment.equipment_no),
                ("EQ Name:", equipment.name),
                ("ZT Code:", equipment.code),
                ("S/N:", equipment.serial_number),
            ]
            for index, (caption, value) in enumerate(rows):
                top = y + head + index * row_height
                row_y = top + (row_height - font) // 2 + LINE
                # The lines beside the QR box stop where the box begins.
                right = box_x if top + row_height > box_y else x + width - LINE
                # The values line up after the widest caption, except the S/N: it
                # starts right after its own short caption, so a long one has room.
                value_x = text_x + (
                    int(len(caption) * font * CHAR_WIDTH) + font // 3 if caption == "S/N:" else caption_width
                )
                room = right - pad - value_x
                out.append(f"^FO{text_x},{row_y}^A0N,{font},{font}^FD{caption}^FS")
                if caption == "EQ Name:":
                    text, high, wide, lines = _name_lines(value, font, room)
                    if text and lines == 2:
                        name_y = top + (row_height - 2 * high) // 2 + LINE
                        out.append(
                            f"^FO{value_x},{name_y}^A0N,{high},{wide}"
                            f"^FB{room},2,0,L^FH\\^FD{_field(text)}^FS"
                        )
                        continue
                    value, value_width = text, wide
                    value_height = font
                elif caption == "S/N:":
                    # A long serial gets a smaller font before it is cut; kept on its row's middle.
                    value, value_height, value_width = _fitted_smaller(value, font, room)
                    row_y = top + (row_height - value_height) // 2 + LINE
                else:
                    value, value_width = _fitted(value, font, room)
                    value_height = font
                if value:
                    out.append(
                        f"^FO{value_x},{row_y}"
                        f"^A0N,{value_height},{value_width}^FH\\^FD{_field(value)}^FS"
                    )
        out += ["^PQ1", "^XZ"]
    return "\n".join(out) + "\n"


def send_to_printer(zpl: str, title: str = "EMA label") -> None:
    """
    Hand raw ZPL to the label printer.

    EMA_LABEL_PRINTER is either the printer's name in Windows on the computer
    running the app, or host:port for a printer on the network (port 9100).
    """
    target = settings.EMA_LABEL_PRINTER.strip()
    if not target:
        raise LabelPrintError("No label printer is configured (EMA_LABEL_PRINTER).")
    data = zpl.encode("utf-8")

    host, _, port = target.rpartition(":")
    if host and port.isdigit():
        try:
            with socket.create_connection((host, int(port)), timeout=5) as connection:
                connection.sendall(data)
        except OSError as error:
            raise LabelPrintError(f"Could not reach the label printer at {target}: {error}") from error
        return
    _send_to_windows_printer(target, data, title)


def _send_to_windows_printer(name: str, data: bytes, title: str) -> None:
    """Spool the bytes untouched (datatype RAW) to a printer installed in Windows."""
    import ctypes
    from ctypes import wintypes

    try:
        spooler = ctypes.WinDLL("winspool.drv", use_last_error=True)
    except (AttributeError, OSError) as error:
        raise LabelPrintError("Printing by printer name needs the app to run on Windows.") from error

    class DocInfo(ctypes.Structure):
        _fields_ = [
            ("pDocName", wintypes.LPWSTR),
            ("pOutputFile", wintypes.LPWSTR),
            ("pDatatype", wintypes.LPWSTR),
        ]

    spooler.OpenPrinterW.argtypes = [wintypes.LPWSTR, ctypes.POINTER(wintypes.HANDLE), ctypes.c_void_p]
    spooler.StartDocPrinterW.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(DocInfo)]
    spooler.StartDocPrinterW.restype = wintypes.DWORD
    spooler.WritePrinter.argtypes = [
        wintypes.HANDLE, ctypes.c_char_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
    ]
    for function in ("StartPagePrinter", "EndPagePrinter", "EndDocPrinter", "ClosePrinter"):
        getattr(spooler, function).argtypes = [wintypes.HANDLE]

    def failed(step: str) -> LabelPrintError:
        return LabelPrintError(f'{step} on "{name}" failed: {ctypes.WinError(ctypes.get_last_error()).strerror}')

    handle = wintypes.HANDLE()
    if not spooler.OpenPrinterW(name, ctypes.byref(handle), None):
        raise LabelPrintError(
            f'Windows has no printer called "{name}" on the computer running the app '
            f"({ctypes.WinError(ctypes.get_last_error()).strerror})."
        )
    try:
        if not spooler.StartDocPrinterW(handle, 1, ctypes.byref(DocInfo(title, None, "RAW"))):
            raise failed("Starting the print job")
        try:
            if not spooler.StartPagePrinter(handle):
                raise failed("Starting the page")
            written = wintypes.DWORD(0)
            if not spooler.WritePrinter(handle, data, len(data), ctypes.byref(written)) or written.value != len(data):
                raise failed("Sending the label")
            spooler.EndPagePrinter(handle)
        finally:
            spooler.EndDocPrinter(handle)
    finally:
        spooler.ClosePrinter(handle)
