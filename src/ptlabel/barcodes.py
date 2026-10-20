"""Barcode encoding (python-barcode) and the layout of the human readable text.

EAN-13, EAN-8 and UPC-A get the usual retail look: longer guard bars, the digits in groups
between them and the first (and for UPC-A the last) digit outside the bars.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import barcode

from .i18n import tr

SAMPLES = {
    "code128": "12345678",
    "code39": "ABC-123",
    "ean13": "400638133393",
    "ean8": "1234567",
    "upca": "03600029145",
    "itf": "123456",
    "codabar": "A123456B",
}

RULES = {
    "code128": tr("letters, digits and the usual characters"),
    "code39": tr("capital letters A–Z, digits, space and - . $ / + %"),
    "ean13": tr("12 digits; the 13th (check digit) is added"),
    "ean8": tr("7 digits; the 8th (check digit) is added"),
    "upca": tr("11 digits; the 12th (check digit) is added"),
    "itf": tr("an even number of digits"),
    "codabar": tr("digits and - $ : / . +, starting and ending with A, B, C or D"),
}


@dataclass(frozen=True)
class TextGroup:
    """Part of the human readable text, centered between two module positions."""
    text: str
    start: int  # module index; negative = in the left quiet zone
    end: int


@dataclass
class Encoded:
    modules: str  # "1" = bar, "0" = space, one character per module
    text: str
    guards: list[tuple[int, int]] = field(default_factory=list)  # module ranges drawn longer
    groups: list[TextGroup] = field(default_factory=list)  # empty: text centered below
    quiet: tuple[int, int] = (10, 10)  # quiet zone left/right in modules


def rule(symbology: str) -> str:
    return RULES.get(symbology, "")


def encode(symbology: str, data: str) -> Encoded:
    """Encode ``data``; raises ValueError with a helpful message when it does not fit."""
    try:
        cls = barcode.get_barcode_class(symbology)
        code = cls(data, add_checksum=False) if symbology == "code39" else cls(data)
        modules = code.build()[0]
        text = code.get_fullcode()
    except Exception as exc:
        name = symbology.upper().replace("EAN", "EAN-").replace("UPCA", "UPC-A")
        raise ValueError(tr("{symbology} needs {rule} ({error})").format(
            symbology=name, rule=rule(symbology), error=exc)) from exc
    encoded = Encoded(modules, text)
    if symbology == "ean13" and len(modules) == 95 and len(text) == 13:
        encoded.guards = [(0, 3), (45, 50), (92, 95)]
        encoded.groups = [TextGroup(text[0], -8, -1), TextGroup(text[1:7], 3, 45), TextGroup(text[7:], 50, 92)]
        encoded.quiet = (11, 7)
    elif symbology == "ean8" and len(modules) == 67 and len(text) == 8:
        encoded.guards = [(0, 3), (31, 36), (64, 67)]
        encoded.groups = [TextGroup(text[:4], 3, 31), TextGroup(text[4:], 36, 64)]
        encoded.quiet = (7, 7)
    elif symbology == "upca" and len(modules) == 95 and len(text) == 12:
        encoded.guards = [(0, 10), (45, 50), (85, 95)]  # incl. the first and last digit's bars
        encoded.groups = [TextGroup(text[0], -8, -1), TextGroup(text[1:6], 10, 45),
                          TextGroup(text[6:11], 50, 85), TextGroup(text[11], 96, 103)]
        encoded.quiet = (9, 9)
    return encoded


def is_valid(symbology: str, data: str) -> bool:
    try:
        encode(symbology, data)
    except ValueError:
        return False
    return True
