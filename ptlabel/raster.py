"""Print jobs in the Brother PT raster command language.

Reference: Brother "Software Developer's Manual - Raster Command Reference
PT-E550W/P750W/P710BT". The printer receives one raster line (128 head pins,
16 bytes) per dot in feed direction.
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

from .tapes import DPI, HEAD_PINS, LINE_BYTES, MM_PER_INCH, Tape

ESC = b"\x1b"

INFO_MEDIA_TYPE = 0x02
INFO_MEDIA_WIDTH = 0x04
INFO_RECOVER = 0x80

MODE_AUTO_CUT = 0x40
MODE_MIRROR = 0x80

ADV_HALF_CUT = 0x04
ADV_NO_CHAIN = 0x08
ADV_HIGH_RES = 0x40


@dataclass
class PrintOptions:
    auto_cut: bool = True
    half_cut: bool = True
    chain: bool = False  # leave the last label in the printer to save tape
    mirror: bool = False
    high_res: bool = False  # 180 x 360 dpi
    margin_mm: float = 2.0  # feed before and after the printed area

    def margin_dots(self) -> int:
        # in high resolution mode the printer counts the margin in 360 dpi dots (verified on a PT-P750W)
        dots = round(self.margin_mm * DPI / MM_PER_INCH)
        return dots * 2 if self.high_res else dots


def packbits(data: bytes) -> bytes:
    """TIFF PackBits compression."""
    out = bytearray()
    i, n = 0, len(data)
    while i < n:
        run = 1
        while i + run < n and run < 128 and data[i + run] == data[i]:
            run += 1
        if run >= 2:
            out.append(257 - run)
            out.append(data[i])
            i += run
            continue
        start = i
        i += 1
        while i < n and i - start < 128 and not (i + 1 < n and data[i] == data[i + 1]):
            i += 1
        out.append(i - start - 1)
        out += data[start:i]
    return bytes(out)


def unpackbits(data: bytes) -> bytes:
    out = bytearray()
    i = 0
    while i < len(data):
        h = data[i]
        i += 1
        if h < 128:
            out += data[i:i + h + 1]
            i += h + 1
        elif h > 128:
            out += bytes([data[i]]) * (257 - h)
            i += 1
    return bytes(out)


def band_to_lines(band: Image.Image, tape: Tape) -> list[bytes]:
    """Convert the printable band into raster lines.

    ``band`` is an "L" image with ink = 255 and exactly ``tape.print_pins`` rows;
    every column becomes one raster line. The top image row lands on the most
    significant bit of the first byte (shifted by the tape margin).
    """
    if band.height != tape.print_pins:
        raise ValueError(f"band height {band.height} != {tape.print_pins} pins")
    ink = band.point(lambda v: 255 if v >= 128 else 0).convert("1", dither=Image.Dither.NONE)
    head = Image.new("1", (max(1, band.width), HEAD_PINS), 0)
    head.paste(ink, (0, tape.margin_pins))
    data = head.transpose(Image.Transpose.TRANSPOSE).tobytes()
    return [data[i:i + LINE_BYTES] for i in range(0, len(data), LINE_BYTES)]


def build_job(pages: list[Image.Image], tape: Tape, options: PrintOptions,
              media_type: int | None = None) -> bytes:
    """Build a complete print job; every page is one label."""
    if not pages:
        raise ValueError("no pages to print")
    out = bytearray(b"\x00" * 100)  # invalidate
    out += ESC + b"@"  # initialize
    out += ESC + b"ia\x01"  # switch to raster mode
    mode = (MODE_AUTO_CUT if options.auto_cut else 0) | (MODE_MIRROR if options.mirror else 0)
    advanced = ((ADV_HALF_CUT if options.half_cut else 0)
                | (0 if options.chain else ADV_NO_CHAIN)
                | (ADV_HIGH_RES if options.high_res else 0))
    flags = INFO_MEDIA_WIDTH | INFO_RECOVER
    if media_type is not None:
        flags |= INFO_MEDIA_TYPE
    last = len(pages) - 1
    for index, page in enumerate(pages):
        lines = band_to_lines(page, tape)
        out += ESC + b"iz" + bytes([flags, media_type or 0, tape.code, 0])
        out += len(lines).to_bytes(4, "little") + bytes([0 if index == 0 else 1, 0])
        out += ESC + b"iM" + bytes([mode])
        if options.auto_cut:
            out += ESC + b"iA\x01"  # cut after every label
        out += ESC + b"iK" + bytes([advanced])
        out += ESC + b"id" + options.margin_dots().to_bytes(2, "little")
        out += b"M\x02"  # TIFF compression
        for line in lines:
            if any(line):
                packed = packbits(line)
                out += b"G" + len(packed).to_bytes(2, "little") + packed
            else:
                out += b"Z"
        out += b"\x1a" if index == last else b"\x0c"
    return bytes(out)
