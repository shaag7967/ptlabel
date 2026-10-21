"""Cable labels: the rendered design ("face") is arranged several times on one strip."""

from __future__ import annotations

from PIL import Image, ImageDraw

from .i18n import tr
from .model import LabelDocument
from .result import RenderResult

FOLD_MARK_MM = 1.0


def compose(doc: LabelDocument, face: RenderResult) -> RenderResult:
    if doc.is_cable_flag:
        return cable_flag(doc, face)
    if doc.is_cable_wrap:
        return cable_wrap(doc, face)
    return face


def _strip(face: RenderResult, length: int, positions: list[int]) -> Image.Image:
    strip = Image.new("L", (length, face.image.height), 0)
    for x in positions:
        strip.paste(face.image, (x, 0))
    return strip


def cable_flag(doc: LabelDocument, face: RenderResult) -> RenderResult:
    """Flag, part around the cable, the same flag again; the flags are stuck back to back."""
    w = face.image.width
    wrap_px = round(doc.wrap_mm * face.scale)
    strip = _strip(face, 2 * w + wrap_px, [0, w + wrap_px])
    if doc.fold_marks:
        draw = ImageDraw.Draw(strip)
        top, bottom = face.band
        mark = max(1, round(FOLD_MARK_MM * face.scale))
        for x in (w, w + wrap_px - 1):
            draw.line((x, top, x, top + mark - 1), fill=255)
            draw.line((x, bottom - mark, x, bottom - 1), fill=255)
    return RenderResult(strip, face.scale, face.tape, face.band, face.margin_px, face.placed, face.warnings,
                        face=(0, w), copies=[w + wrap_px], wrap=(w, w + wrap_px))


def cable_wrap(doc: LabelDocument, face: RenderResult) -> RenderResult:
    """The design ("tile") repeated evenly along the length that is wound around the cable."""
    w = face.image.width
    length = max(w, round(doc.wrap_length_mm * face.scale))
    count = max(1, length // w)
    gap = (length - count * w) / count  # spread the rest evenly, half a gap at both ends
    positions = [round(gap / 2 + i * (w + gap)) for i in range(count)]
    warnings = list(face.warnings)
    if count < 2:
        warnings.append(tr("Cable wrap: the design fits around the cable only once – make it shorter, "
                           "e.g. turn the text across the tape"))
    first = positions[0]
    placed = [p.shifted(first) for p in face.placed]
    return RenderResult(_strip(face, length, positions), face.scale, face.tape, face.band, face.margin_px,
                        placed, warnings, face=(first, first + w), copies=[x - first for x in positions[1:]])
