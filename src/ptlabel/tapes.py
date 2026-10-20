"""Tape and print head geometry of the Brother PT-P750W (and compatible PT models)."""

from __future__ import annotations

from dataclasses import dataclass

from .i18n import tr

DPI = 180  # print head resolution (across the tape and in feed direction)
HEAD_PINS = 128  # pins on the print head
LINE_BYTES = HEAD_PINS // 8
MM_PER_INCH = 25.4


@dataclass(frozen=True)
class Tape:
    width_mm: float  # nominal tape width
    code: int  # width code used by the printer (status byte 10, ESC i z n3)
    margin_pins: int  # unprintable pins on each side of the printable band
    print_pins: int  # printable pins across the tape

    @property
    def label(self) -> str:
        return f"{self.width_mm:g} mm"

    @property
    def print_mm(self) -> float:
        return self.print_pins * MM_PER_INCH / DPI

    @property
    def band_top_mm(self) -> float:
        """Distance from the upper tape edge to the printable band."""
        return max(0.0, (self.width_mm - self.print_mm) / 2)


# Print area per tape width, from Brother's raster command reference.
TAPES = [
    Tape(3.5, 4, 52, 24),
    Tape(6, 6, 48, 32),
    Tape(9, 9, 39, 50),
    Tape(12, 12, 29, 70),
    Tape(18, 18, 8, 112),
    Tape(24, 24, 0, 128),
]


def tape_for_width(width_mm: float) -> Tape:
    return min(TAPES, key=lambda t: abs(t.width_mm - width_mm))


def tape_for_code(code: int) -> Tape | None:
    for tape in TAPES:
        if tape.code == code:
            return tape
    return None


MEDIA_TYPES = {
    0x00: tr("no tape"),
    0x01: tr("laminated"),
    0x03: tr("non-laminated"),
    0x11: tr("heat-shrink tube 2:1"),
    0x17: tr("heat-shrink tube 3:1"),
    0xFF: tr("incompatible"),
}

# code -> (name, preview colour)
TAPE_COLORS = {
    0x01: (tr("White"), "#ffffff"),
    0x02: (tr("Other"), "#d8d8d8"),
    0x03: (tr("Clear"), "#e9eef0"),
    0x04: (tr("Red"), "#d7262c"),
    0x05: (tr("Blue"), "#2160c4"),
    0x06: (tr("Yellow"), "#f8d616"),
    0x07: (tr("Green"), "#2f9e48"),
    0x08: (tr("Black"), "#1b1b1b"),
    0x09: (tr("Clear"), "#e9eef0"),
    0x20: (tr("Matte white"), "#f5f5f1"),
    0x21: (tr("Matte clear"), "#e6eaea"),
    0x22: (tr("Matte silver"), "#c3c6c8"),
    0x23: (tr("Satin gold"), "#d5b25c"),
    0x24: (tr("Satin silver"), "#cbced1"),
    0x30: (tr("Blue"), "#2b70d8"),
    0x31: (tr("Red"), "#e03a3f"),
    0x40: (tr("Fluorescent orange"), "#ff7b1c"),
    0x41: (tr("Fluorescent yellow"), "#e9ff2b"),
    0x50: (tr("Berry pink"), "#e0467c"),
    0x51: (tr("Light gray"), "#c9c9c9"),
    0x52: (tr("Lime green"), "#9cd43b"),
    0x60: (tr("Yellow"), "#f6d931"),
    0x61: (tr("Pink"), "#f39cc1"),
    0x62: (tr("Blue"), "#70a9e1"),
    0x70: (tr("White"), "#ffffff"),
    0x90: (tr("White"), "#ffffff"),
    0x91: (tr("Yellow"), "#f8d616"),
    0xF0: (tr("Cleaning tape"), "#ffffff"),
    0xF1: (tr("Stencil"), "#dfe7ef"),
    0xFF: (tr("incompatible"), "#d8d8d8"),
}

TEXT_COLORS = {
    0x01: (tr("White"), "#ffffff"),
    0x02: (tr("Other"), "#444444"),
    0x04: (tr("Red"), "#d7262c"),
    0x05: (tr("Blue"), "#2160c4"),
    0x08: (tr("Black"), "#111111"),
    0x0A: (tr("Gold"), "#b8902f"),
    0x62: (tr("Blue"), "#2160c4"),
    0xF0: (tr("Cleaning"), "#111111"),
    0xF1: (tr("Stencil"), "#111111"),
    0xFF: (tr("incompatible"), "#111111"),
}
