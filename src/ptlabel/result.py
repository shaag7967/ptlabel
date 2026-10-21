"""Result of rendering a label: the bitmap and where every object ended up."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from PIL import Image

from .model import LabelObject
from .tapes import Tape


@dataclass
class Placed:
    obj: LabelObject
    box: tuple[int, int, int, int]  # pixel box (x0, y0, x1, y1) in the rendered image
    size_pt: float | None = None  # effective font size of text objects

    def shifted(self, dx: int) -> Placed:
        x0, y0, x1, y1 = self.box
        return replace(self, box=(x0 + dx, y0, x1 + dx, y1))


@dataclass
class RenderResult:
    image: Image.Image  # "L", 255 = ink; full tape width x label length
    scale: float  # pixels per mm
    tape: Tape
    band: tuple[int, int]  # printable rows [top, bottom)
    margin_px: int
    placed: list[Placed] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    face: tuple[int, int] | None = None  # editable area [x0, x1); None = the whole label
    copies: list[int] = field(default_factory=list)  # x offsets of repeated copies of the face
    wrap: tuple[int, int] | None = None  # cable flag: part wrapped around the cable [x0, x1)

    @property
    def length_mm(self) -> float:
        return self.image.width / self.scale

    @property
    def face_box(self) -> tuple[int, int]:
        return self.face or (0, self.image.width)

    @property
    def face_mm(self) -> float:
        x0, x1 = self.face_box
        return (x1 - x0) / self.scale
