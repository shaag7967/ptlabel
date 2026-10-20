"""Rendering of a label document into a bitmap (ink = 255)."""

from __future__ import annotations

import base64
import io
import math
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache

import barcode
import segno
from PIL import Image, ImageDraw, ImageOps

from . import fonts
from .i18n import tr
from .model import (BarcodeObject, FrameObject, ImageObject, LabelDocument, LabelObject, LineObject,
                    QRCodeObject, TextObject, expand)
from .tapes import DPI, MM_PER_INCH, Tape

PT_TO_MM = MM_PER_INCH / 72
MIN_CONTENT_MM = 4.0


def _threshold(v: int) -> int:
    return 255 if v >= 128 else 0


@dataclass
class Placed:
    obj: LabelObject
    box: tuple[int, int, int, int]  # pixel box (x0, y0, x1, y1) in the rendered image
    size_pt: float | None = None  # effective font size of text objects


@dataclass
class RenderResult:
    image: Image.Image  # "L", 255 = ink; full tape width x label length
    scale: float  # pixels per mm
    tape: Tape
    band: tuple[int, int]  # printable rows [top, bottom)
    margin_px: int
    placed: list[Placed] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def length_mm(self) -> float:
        return self.image.width / self.scale


@dataclass
class _Ctx:
    counter: int
    now: datetime
    band_h: int
    warnings: list[str]


def render(doc: LabelDocument, dpi: int = DPI, counter: int | None = None,
           now: datetime | None = None) -> RenderResult:
    scale = dpi / MM_PER_INCH
    tape = doc.tape
    tape_px = round(tape.width_mm * scale)
    band_top = round(tape.band_top_mm * scale)
    band_h = round(tape.print_pins * dpi / DPI)
    ctx = _Ctx(doc.counter_start if counter is None else counter, now or datetime.now(), band_h, [])

    items = []
    for obj in doc.objects:
        size_pt = None
        try:
            img, opaque, size_pt = _render_object(obj, scale, ctx)
        except Exception as exc:  # keep the editor usable on bad input
            ctx.warnings.append(f"{obj.title}: {exc}")
            img, opaque = _error_box(scale), False
        img = _rotate(img, obj.rotation)
        x = round(obj.x * scale)
        if isinstance(obj, TextObject) and obj.auto_size:
            y = band_top + (band_h - img.height) // 2
        else:
            y = round(obj.y * scale)
        items.append((obj, img, x, y, opaque, size_pt))

    margin_px = round(doc.margin_mm * scale)
    min_length = 2 * margin_px + round(MIN_CONTENT_MM * scale)
    if doc.auto_length:
        right = max((x + img.width for _, img, x, *_ in items), default=0)
        length_px = max(right + margin_px, min_length)
    else:
        length_px = max(round(doc.length_mm * scale), 2 * margin_px + 1)

    canvas = Image.new("L", (length_px, tape_px), 0)
    placed = []
    for obj, img, x, y, opaque, size_pt in items:
        if opaque:
            canvas.paste(img, (x, y))
        else:
            canvas.paste(255, (x, y), img)
        box = (x, y, x + img.width, y + img.height)
        placed.append(Placed(obj, box, size_pt))
        if (box[1] < band_top or box[3] > band_top + band_h or box[0] < margin_px
                or box[2] > length_px - margin_px):
            ctx.warnings.append(tr("{object} extends beyond the printable area").format(object=obj.title))
    canvas = canvas.point(_threshold)
    return RenderResult(canvas, scale, tape, (band_top, band_top + band_h), margin_px, placed, ctx.warnings)


def print_pages(doc: LabelDocument, now: datetime | None = None) -> list[Image.Image]:
    """Printable bands (one per copy) ready for :func:`raster.build_job`."""
    dpi = DPI * 2 if doc.high_res else DPI
    now = now or datetime.now()
    copies = max(1, int(doc.copies))
    if doc.uses_counter():
        return [_band(render(doc, dpi, doc.counter_start + i, now), dpi) for i in range(copies)]
    return [_band(render(doc, dpi, None, now), dpi)] * copies


def _band(result: RenderResult, dpi: int) -> Image.Image:
    top, bottom = result.band
    x0 = result.margin_px
    x1 = max(x0 + 1, result.image.width - result.margin_px)
    band = result.image.crop((x0, top, x1, bottom))
    if dpi != DPI:  # high resolution: 360 dpi along the tape, 180 dpi across
        band = band.resize((band.width, result.tape.print_pins), Image.Resampling.BOX).point(_threshold)
    return band


def _rotate(img: Image.Image, rotation: int) -> Image.Image:
    ops = {90: Image.Transpose.ROTATE_90, 180: Image.Transpose.ROTATE_180, 270: Image.Transpose.ROTATE_270}
    op = ops.get(int(rotation) % 360)
    return img.transpose(op) if op is not None else img


def _error_box(scale: float) -> Image.Image:
    size = max(4, round(4 * scale))
    img = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, size - 1, size - 1), outline=255)
    draw.line((0, 0, size - 1, size - 1), fill=255)
    draw.line((0, size - 1, size - 1, 0), fill=255)
    return img


def _render_object(obj: LabelObject, scale: float, ctx: _Ctx):
    """Return (image, opaque, effective size in pt)."""
    if isinstance(obj, TextObject):
        return _render_text(obj, scale, ctx)
    if isinstance(obj, QRCodeObject):
        return _render_qr(obj, scale, ctx), False, None
    if isinstance(obj, BarcodeObject):
        return _render_barcode(obj, scale, ctx), False, None
    if isinstance(obj, ImageObject):
        return _render_image(obj, scale), False, None
    if isinstance(obj, FrameObject):
        return _render_frame(obj, scale), False, None
    if isinstance(obj, LineObject):
        return _render_line(obj, scale), False, None
    raise TypeError(f"unknown object {obj!r}")


# --- text -------------------------------------------------------------------

def _text_block(obj: TextObject, text: str, size_px: int) -> Image.Image:
    font, faux_bold = fonts.get_font(obj.font, size_px, obj.bold, obj.italic)
    lines = text.split("\n")
    ascent, descent = font.getmetrics()
    line_h = ascent + descent
    pitch = max(1, round(line_h * obj.line_spacing))
    widths = [font.getlength(line) for line in lines]
    width = math.ceil(max(widths, default=0))
    height = pitch * (len(lines) - 1) + line_h
    pad = math.ceil(size_px * 0.5)
    stroke = max(1, round(size_px / 28)) if faux_bold else 0

    img = Image.new("L", (width + 2 * pad, height + 2 * pad), 0)
    draw = ImageDraw.Draw(img)
    draw.fontmode = "1"  # crisp, hinted glyphs for the 180 dpi head
    for i, (line, w) in enumerate(zip(lines, widths)):
        if obj.align == "center":
            x = pad + (width - w) / 2
        elif obj.align == "right":
            x = pad + width - w
        else:
            x = pad
        y = pad + i * pitch
        draw.text((x, y), line, font=font, fill=255, anchor="la", stroke_width=stroke)
        if obj.underline and line:
            thickness = max(1, round(size_px / 16))
            uy = y + ascent + max(1, round(descent / 3))
            draw.rectangle((x, uy, x + w - 1, uy + thickness - 1), fill=255)

    # keep the metric box, extended by any ink outside of it (italic overhang etc.)
    ink = img.getbbox() or (pad, pad, pad + 1, pad + 1)
    box = (min(ink[0], pad), min(ink[1], pad), max(ink[2], pad + max(width, 1)), max(ink[3], pad + height))
    img = img.crop(box)
    if obj.invert:
        border = max(1, round(size_px * 0.12))
        img = ImageOps.invert(ImageOps.expand(img, border, fill=0))
    return img


def _render_text(obj: TextObject, scale: float, ctx: _Ctx):
    text = expand(obj.text, ctx.counter, ctx.now)
    if obj.auto_size:
        # extent across the tape grows linearly with the font size: measure once, then correct
        def extent(img: Image.Image) -> int:
            return img.width if obj.rotation % 180 else img.height

        reference = 100
        size_px = max(3, int(reference * ctx.band_h / max(1, extent(_text_block(obj, text, reference)))))
        img = _text_block(obj, text, size_px)
        while extent(img) > ctx.band_h and size_px > 3:
            size_px -= 1
            img = _text_block(obj, text, size_px)
    else:
        size_px = max(3, round(obj.size * PT_TO_MM * scale))
        img = _text_block(obj, text, size_px)
    return img, obj.invert, round(size_px / (PT_TO_MM * scale), 1)


# --- codes ------------------------------------------------------------------

def _render_qr(obj: QRCodeObject, scale: float, ctx: _Ctx) -> Image.Image:
    data = expand(obj.data, ctx.counter, ctx.now) or " "
    qr = segno.make_qr(data, error=obj.error.lower(), boost_error=False)
    n = qr.symbol_size(border=0)[0]
    box = max(1, round(obj.size * scale))
    module = max(1, box // n)  # whole dots per module keep the code readable
    if module * DPI / (scale * MM_PER_INCH) < 2:
        ctx.warnings.append(tr("QR code: modules smaller than 2 dots – make the QR code larger"))
    raw = bytes(255 if v else 0 for row in qr.matrix for v in row)
    symbol = Image.frombytes("L", (n, n), raw).resize((n * module, n * module), Image.Resampling.NEAREST)
    img = Image.new("L", (max(box, symbol.width),) * 2, 0)
    offset = (img.width - symbol.width) // 2
    img.paste(symbol, (offset, offset))
    return img


def _render_barcode(obj: BarcodeObject, scale: float, ctx: _Ctx) -> Image.Image:
    data = expand(obj.data, ctx.counter, ctx.now)
    kwargs = {"add_checksum": False} if obj.symbology == "code39" else {}
    try:
        code = barcode.get(obj.symbology, data, **kwargs)
        modules = code.build()[0]
    except Exception as exc:
        raise ValueError(tr("invalid data for {symbology}: {error}").format(
            symbology=obj.symbology.upper(), error=exc)) from exc
    unit = max(1, round(obj.module * scale * MM_PER_INCH / DPI))
    quiet = 10 * unit
    width = len(modules) * unit + 2 * quiet

    text_img = None
    if obj.show_text:
        text_px = max(3, round(obj.text_size * PT_TO_MM * scale))
        font, _ = fonts.get_font("", text_px)
        label = code.get_fullcode() if hasattr(code, "get_fullcode") else data
        ascent, descent = font.getmetrics()
        text_img = Image.new("L", (max(width, math.ceil(font.getlength(label))), ascent + descent), 0)
        draw = ImageDraw.Draw(text_img)
        draw.fontmode = "1"
        draw.text((text_img.width / 2, 0), label, font=font, fill=255, anchor="ma")
        width = text_img.width

    gap = max(1, round(0.3 * scale)) if text_img else 0
    text_h = text_img.height + gap if text_img else 0
    bar_h = max(1, round(obj.height * scale) - text_h)  # height includes the human readable text
    img = Image.new("L", (width, bar_h + text_h), 0)
    draw = ImageDraw.Draw(img)
    x = (width - len(modules) * unit) // 2
    for bit in modules:
        if bit == "1":
            draw.rectangle((x, 0, x + unit - 1, bar_h - 1), fill=255)
        x += unit
    if text_img:
        img.paste(text_img, ((width - text_img.width) // 2, bar_h + gap))
    return img


# --- graphics ---------------------------------------------------------------

@lru_cache(maxsize=16)
def _decode_image(data: str) -> Image.Image:
    img = Image.open(io.BytesIO(base64.b64decode(data)))
    img.load()
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        background = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(background, img)
    return img.convert("L")


def image_aspect(obj: ImageObject) -> float | None:
    if not obj.data:
        return None
    src = _decode_image(obj.data)
    return src.width / src.height


def _render_image(obj: ImageObject, scale: float) -> Image.Image:
    w = max(1, round(obj.width * scale))
    h = max(1, round(obj.height * scale))
    if not obj.data:
        img = Image.new("L", (w, h), 0)
        ImageDraw.Draw(img).rectangle((0, 0, w - 1, h - 1), outline=255)
        return img
    src = _decode_image(obj.data)
    gray = src.resize((w, h), Image.Resampling.LANCZOS)
    if obj.dither:
        bw = gray.convert("1", dither=Image.Dither.FLOYDSTEINBERG).convert("L")
    else:
        bw = gray.point(lambda v: 255 if v >= obj.threshold else 0)
    ink = ImageOps.invert(bw)  # dark pixels print
    return ImageOps.invert(ink) if obj.invert else ink


def _render_frame(obj: FrameObject, scale: float) -> Image.Image:
    w = max(1, round(obj.width * scale))
    h = max(1, round(obj.height * scale))
    t = max(1, round(obj.thickness * scale))
    img = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(img)
    radius = round(obj.radius * scale)
    if obj.fill:
        draw.rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
    else:
        draw.rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, outline=255, width=t)
    return img


def _render_line(obj: LineObject, scale: float) -> Image.Image:
    length = max(1, round(obj.length * scale))
    t = max(1, round(obj.thickness * scale))
    return Image.new("L", (t, length) if obj.vertical else (length, t), 255)
