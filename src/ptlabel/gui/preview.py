"""Colored preview bitmaps of a rendered label."""

from __future__ import annotations

from PIL import Image, ImageDraw

from ..render import RenderResult

SHADE = (40, 40, 40)


def colorize(result: RenderResult, tape_rgb, ink_rgb) -> Image.Image:
    """The label in tape and ink color."""
    img = Image.new("RGB", result.image.size, tape_rgb)
    img.paste(ink_rgb, (0, 0), result.image)
    return img


def preview(result: RenderResult, tape_rgb, ink_rgb) -> Image.Image:
    """Like :func:`colorize`, with the unprintable tape edges and margins shaded."""
    img = colorize(result, tape_rgb, ink_rgb)
    shade = Image.new("L", img.size, 0)
    draw = ImageDraw.Draw(shade)
    w, h = img.size
    top, bottom = result.band
    if top > 0:
        draw.rectangle((0, 0, w - 1, top - 1), fill=110)
    if bottom < h:
        draw.rectangle((0, bottom, w - 1, h - 1), fill=110)
    m = result.margin_px
    if m > 0:
        draw.rectangle((0, top, m - 1, bottom - 1), fill=70)
        draw.rectangle((w - m, top, w - 1, bottom - 1), fill=70)
    img.paste(SHADE, (0, 0), shade)
    return img
