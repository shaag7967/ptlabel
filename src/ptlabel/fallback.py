"""Fallback fonts for characters that the chosen font does not contain.

Text is split into runs: every character uses the chosen font if it has a glyph for it, otherwise
the first font with a glyph – preferring fonts with a large character set – so that arrows, check
marks, Greek or CJK characters print instead of empty boxes.
"""

from __future__ import annotations

import threading
import unicodedata
from functools import lru_cache

from PIL import ImageFont

from . import fonts
from .fonts import Face

PROBE_PX = 32
MISSING = "\U0010FFFF"  # never mapped: renders the font's "missing glyph" shape
# Fonts with a large character set are tried first, in this order, then all others.
PREFERRED = ["DejaVu Sans", "Noto Sans", "Liberation Sans", "Arial", "Segoe UI", "Cantarell", "Ubuntu",
             "Noto Sans Math", "Noto Sans Symbols", "Noto Sans Symbols 2", "Segoe UI Symbol", "Symbola",
             "FreeSans", "FreeSerif", "Arial Unicode MS", "Droid Sans Fallback", "Noto Sans CJK JP",
             "Microsoft YaHei", "MS Gothic"]
EXCLUDED = ("Color Emoji",)  # colored glyphs do not print in one color


def _shape(font: ImageFont.FreeTypeFont, char: str) -> tuple:
    mask = font.getmask(char)
    return mask.size, bytes(mask)


@lru_cache(maxsize=None)
def _missing_shape(path: str, index: int) -> tuple | None:
    try:
        return _shape(fonts.load_face(Face(path, index, "", ""), PROBE_PX), MISSING)
    except Exception:
        return None


@lru_cache(maxsize=65536)
def _has_glyph(path: str, index: int, char: str) -> bool:
    missing = _missing_shape(path, index)
    if missing is None:
        return False
    try:
        return _shape(fonts.load_face(Face(path, index, "", ""), PROBE_PX), char) != missing
    except Exception:
        return False


def has_glyph(face: Face, char: str) -> bool:
    if char.isspace() or unicodedata.category(char) in ("Cc", "Cf"):
        return True  # nothing to draw
    return _has_glyph(face.path, face.index, char)


class FallbackFinder:
    """Finds, and remembers per character, the first font family that has a glyph."""

    def __init__(self, registry: fonts.FontRegistry):
        self.registry = registry
        self._lock = threading.Lock()
        self._generation = -1
        self._families: dict[str, str | None] = {}

    def _candidates(self) -> list[str]:
        names = self.registry.families(include_all=True)
        names = [n for n in names if not any(word in n for word in EXCLUDED)]
        preferred = [p for p in PREFERRED if p in names]
        return preferred + [n for n in names if n not in preferred]

    def family_for(self, char: str) -> str | None:
        with self._lock:
            if self._generation != self.registry.generation:
                self._families, self._generation = {}, self.registry.generation
            if char not in self._families:
                self._families[char] = next(
                    (name for name in self._candidates()
                     if has_glyph(self.registry.resolve(name, False, False), char)), None)
            return self._families[char]

    def face_for(self, char: str, bold: bool, italic: bool) -> Face | None:
        family = self.family_for(char)
        if family is None:
            return None
        face = self.registry.resolve(family, bold, italic)
        return face if face is not None and has_glyph(face, char) else self.registry.resolve(family, False, False)


FINDER = FallbackFinder(fonts.REGISTRY)


def runs(text: str, family: str, size_px: int, bold: bool = False, italic: bool = False):
    """[(font, needs_faux_bold, text), …] that together draw ``text``."""
    primary = fonts.REGISTRY.resolve(family, bold, italic)
    if primary is None:  # no fonts installed at all
        font, faux = fonts.get_font(family, size_px, bold, italic)
        return [(font, faux, text)]
    result: list[list] = []
    for char in text:
        face = primary
        if not has_glyph(primary, char):
            face = FINDER.face_for(char, bold, italic) or primary  # nothing has it: keep the box
        if result and result[-1][0] == face:
            result[-1][1] += char
        else:
            result.append([face, char])
    return [(fonts.load_face(face, size_px), bold and not face.is_bold, chunk) for face, chunk in result]


def missing(text: str, family: str, bold: bool = False, italic: bool = False) -> list[str]:
    """Characters of ``text`` that no installed font can draw."""
    primary = fonts.REGISTRY.resolve(family, bold, italic)
    if primary is None:
        return []
    seen = []
    for char in dict.fromkeys(text):
        if not has_glyph(primary, char) and FINDER.family_for(char) is None:
            seen.append(char)
    return seen
