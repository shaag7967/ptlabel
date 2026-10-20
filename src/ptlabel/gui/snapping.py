"""Snapping of moved objects to the tape center, the margins and other objects.

All coordinates are pixels of the rendered label image.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..render import RenderResult

Box = tuple[float, float, float, float]


@dataclass(frozen=True)
class Guide:
    vertical: bool  # True: line at x = position, False: line at y = position
    position: float


def _targets(result: RenderResult, others: list[Box]) -> tuple[list[float], list[float]]:
    width = result.image.width
    top, bottom = result.band
    xs = [result.margin_px, width - result.margin_px, width / 2]
    ys = [top, bottom, (top + bottom) / 2]
    for x0, y0, x1, y1 in others:
        xs += [x0, x1, (x0 + x1) / 2]
        ys += [y0, y1, (y0 + y1) / 2]
    return xs, ys


def _best(anchors: list[float], targets: list[float], threshold: float) -> tuple[float, list[float]]:
    """Smallest correction that puts one of ``anchors`` onto a target, and the matched targets."""
    best = None
    for anchor in anchors:
        for target in targets:
            delta = target - anchor
            if abs(delta) <= threshold and (best is None or abs(delta) < abs(best)):
                best = delta
    if best is None:
        return 0.0, []
    lines = sorted({t for t in targets for a in anchors if abs(a + best - t) < 0.5})
    return best, lines


def snap(box: Box, result: RenderResult, others: list[Box], threshold: float,
         snap_y: bool = True) -> tuple[float, float, list[Guide]]:
    """Return (dx, dy, guides) that align ``box`` with the nearest guide within ``threshold``."""
    xs, ys = _targets(result, others)
    x0, y0, x1, y1 = box
    dx, vlines = _best([x0, (x0 + x1) / 2, x1], xs, threshold)
    dy, hlines = _best([y0, (y0 + y1) / 2, y1], ys, threshold) if snap_y else (0.0, [])
    guides = [Guide(True, x) for x in vlines] + [Guide(False, y) for y in hlines]
    return dx, dy, guides
