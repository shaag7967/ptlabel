"""Label document: tape settings, print options and the objects placed on the label."""

from __future__ import annotations

import json
import string
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import ClassVar

from .raster import PrintOptions
from .tapes import Tape, tape_for_width

FILE_FORMAT = "ptlabel"
FILE_VERSION = 1


@dataclass(frozen=True)
class Prop:
    """Describes an editable attribute for the property panel."""
    attr: str
    label: str
    kind: str  # text, multiline, float, int, bool, choice, font, image
    options: tuple = ()  # (min, max, step) for numbers, ((value, label), ...) for choices


ROTATIONS = ((0, "0°"), (90, "90°"), (180, "180°"), (270, "270°"))
POSITION_PROPS = [
    Prop("x", "X (mm)", "float", (-50, 1000, 0.5)),
    Prop("y", "Y (mm)", "float", (-50, 50, 0.5)),
    Prop("rotation", "Drehung", "choice", ROTATIONS),
]


@dataclass
class LabelObject:
    kind: ClassVar[str] = ""
    title: ClassVar[str] = ""
    PROPS: ClassVar[list[Prop]] = []

    x: float = 2.0  # mm from the left label edge
    y: float = 1.0  # mm from the upper tape edge
    rotation: int = 0  # counter-clockwise, multiple of 90

    @classmethod
    def props(cls) -> list[Prop]:
        return cls.PROPS + POSITION_PROPS

    def to_dict(self) -> dict:
        return {"type": self.kind, **asdict(self)}

    def copy(self) -> LabelObject:
        return type(self)(**asdict(self))

    def resize(self, orig: LabelObject, fx: float, fy: float) -> None:
        """Scale relative to ``orig`` by fx/fy along the unrotated object axes."""


@dataclass
class TextObject(LabelObject):
    kind: ClassVar[str] = "text"
    title: ClassVar[str] = "Text"
    PROPS: ClassVar[list[Prop]] = [
        Prop("text", "Text", "multiline"),
        Prop("font", "Schriftart", "font"),
        Prop("size", "Größe (pt)", "float", (3, 300, 1)),
        Prop("auto_size", "Größe automatisch (Bandhöhe füllen)", "bool"),
        Prop("bold", "Fett", "bool"),
        Prop("italic", "Kursiv", "bool"),
        Prop("underline", "Unterstrichen", "bool"),
        Prop("invert", "Invertiert (weiß auf schwarz)", "bool"),
        Prop("align", "Ausrichtung", "choice", (("left", "Links"), ("center", "Zentriert"), ("right", "Rechts"))),
        Prop("line_spacing", "Zeilenabstand", "float", (0.5, 3, 0.1)),
    ]

    text: str = "Text"
    font: str = ""
    size: float = 12.0
    auto_size: bool = True
    bold: bool = False
    italic: bool = False
    underline: bool = False
    invert: bool = False
    align: str = "left"
    line_spacing: float = 1.0

    def resize(self, orig, fx, fy):
        self.size = round(max(3.0, orig.size * fy), 1)
        self.auto_size = False


@dataclass
class QRCodeObject(LabelObject):
    kind: ClassVar[str] = "qrcode"
    title: ClassVar[str] = "QR-Code"
    PROPS: ClassVar[list[Prop]] = [
        Prop("data", "Inhalt", "multiline"),
        Prop("size", "Größe (mm)", "float", (2, 100, 0.5)),
        Prop("error", "Fehlerkorrektur", "choice", (("L", "L (7 %)"), ("M", "M (15 %)"), ("Q", "Q (25 %)"), ("H", "H (30 %)"))),
    ]

    data: str = "https://example.com"
    size: float = 9.0
    error: str = "M"

    def resize(self, orig, fx, fy):
        self.size = round(max(2.0, orig.size * (fx + fy) / 2), 1)


BARCODE_TYPES = (
    ("code128", "Code 128"),
    ("code39", "Code 39"),
    ("ean13", "EAN-13"),
    ("ean8", "EAN-8"),
    ("upca", "UPC-A"),
    ("itf", "ITF (2 aus 5)"),
    ("codabar", "Codabar"),
)


@dataclass
class BarcodeObject(LabelObject):
    kind: ClassVar[str] = "barcode"
    title: ClassVar[str] = "Barcode"
    PROPS: ClassVar[list[Prop]] = [
        Prop("data", "Inhalt", "text"),
        Prop("symbology", "Typ", "choice", BARCODE_TYPES),
        Prop("height", "Höhe inkl. Klartext (mm)", "float", (1, 100, 0.5)),
        Prop("module", "Modulbreite (Punkte)", "int", (1, 6, 1)),
        Prop("show_text", "Klartext anzeigen", "bool"),
        Prop("text_size", "Klartext-Größe (pt)", "float", (3, 30, 0.5)),
    ]

    data: str = "12345678"
    symbology: str = "code128"
    height: float = 6.0
    module: int = 2
    show_text: bool = True
    text_size: float = 6.0

    def resize(self, orig, fx, fy):
        self.height = round(max(1.0, orig.height * fy), 1)
        self.module = max(1, min(6, round(orig.module * fx)))


@dataclass
class ImageObject(LabelObject):
    kind: ClassVar[str] = "image"
    title: ClassVar[str] = "Bild"
    PROPS: ClassVar[list[Prop]] = [
        Prop("data", "Bild", "image"),
        Prop("width", "Breite (mm)", "float", (1, 500, 0.5)),
        Prop("height", "Höhe (mm)", "float", (1, 50, 0.5)),
        Prop("keep_aspect", "Seitenverhältnis beibehalten", "bool"),
        Prop("dither", "Rastern (für Fotos)", "bool"),
        Prop("threshold", "Schwellwert (0–255)", "int", (1, 254, 8)),
        Prop("invert", "Invertieren", "bool"),
    ]

    data: str = ""  # base64 encoded PNG
    name: str = ""
    width: float = 10.0
    height: float = 9.0
    keep_aspect: bool = True
    dither: bool = False
    threshold: int = 128
    invert: bool = False

    def resize(self, orig, fx, fy):
        if self.keep_aspect:
            fx = fy = (fx + fy) / 2
        self.width = round(max(1.0, orig.width * fx), 1)
        self.height = round(max(1.0, orig.height * fy), 1)


@dataclass
class FrameObject(LabelObject):
    kind: ClassVar[str] = "frame"
    title: ClassVar[str] = "Rahmen"
    PROPS: ClassVar[list[Prop]] = [
        Prop("width", "Breite (mm)", "float", (1, 1000, 0.5)),
        Prop("height", "Höhe (mm)", "float", (1, 50, 0.5)),
        Prop("thickness", "Linienstärke (mm)", "float", (0.1, 5, 0.1)),
        Prop("radius", "Eckenradius (mm)", "float", (0, 20, 0.5)),
        Prop("fill", "Gefüllt", "bool"),
    ]

    width: float = 30.0
    height: float = 9.0
    thickness: float = 0.4
    radius: float = 0.0
    fill: bool = False

    def resize(self, orig, fx, fy):
        self.width = round(max(1.0, orig.width * fx), 1)
        self.height = round(max(1.0, orig.height * fy), 1)


@dataclass
class LineObject(LabelObject):
    kind: ClassVar[str] = "line"
    title: ClassVar[str] = "Linie"
    PROPS: ClassVar[list[Prop]] = [
        Prop("length", "Länge (mm)", "float", (0.5, 1000, 0.5)),
        Prop("thickness", "Linienstärke (mm)", "float", (0.1, 10, 0.1)),
        Prop("vertical", "Senkrecht", "bool"),
    ]

    length: float = 20.0
    thickness: float = 0.4
    vertical: bool = False

    def resize(self, orig, fx, fy):
        self.length = round(max(0.5, orig.length * (fy if self.vertical else fx)), 1)


OBJECT_TYPES: dict[str, type[LabelObject]] = {
    cls.kind: cls for cls in (TextObject, QRCodeObject, BarcodeObject, ImageObject, FrameObject, LineObject)
}


def object_from_dict(data: dict) -> LabelObject:
    cls = OBJECT_TYPES[data["type"]]
    known = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class LabelDocument:
    tape_mm: float = 12.0
    auto_length: bool = True
    length_mm: float = 50.0
    margin_mm: float = 2.0
    copies: int = 1
    counter_start: int = 1
    auto_cut: bool = True
    half_cut: bool = True
    chain: bool = False
    mirror: bool = False
    high_res: bool = False
    objects: list[LabelObject] = field(default_factory=list)

    @property
    def tape(self) -> Tape:
        return tape_for_width(self.tape_mm)

    def print_options(self) -> PrintOptions:
        return PrintOptions(auto_cut=self.auto_cut, half_cut=self.half_cut, chain=self.chain,
                            mirror=self.mirror, high_res=self.high_res, margin_mm=self.margin_mm)

    def uses_counter(self) -> bool:
        return any("{nr" in getattr(obj, attr, "") for obj in self.objects for attr in ("text", "data")
                   if isinstance(getattr(obj, attr, None), str))

    def to_dict(self) -> dict:
        data = {"format": FILE_FORMAT, "version": FILE_VERSION}
        data.update({f.name: getattr(self, f.name) for f in fields(self) if f.name != "objects"})
        data["objects"] = [obj.to_dict() for obj in self.objects]
        return data

    @classmethod
    def from_dict(cls, data: dict) -> LabelDocument:
        if data.get("format") != FILE_FORMAT:
            raise ValueError("Keine PT-Label-Datei")
        known = {f.name for f in fields(cls)} - {"objects"}
        doc = cls(**{k: v for k, v in data.items() if k in known})
        doc.objects = [object_from_dict(o) for o in data.get("objects", []) if o.get("type") in OBJECT_TYPES]
        return doc

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=1)

    @classmethod
    def from_json(cls, text: str) -> LabelDocument:
        return cls.from_dict(json.loads(text))

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> LabelDocument:
        return cls.from_json(Path(path).read_text(encoding="utf-8"))


class _DateValue:
    def __init__(self, value: datetime, default: str):
        self.value = value
        self.default = default

    def __format__(self, spec: str) -> str:
        return self.value.strftime(spec or self.default)


class _Formatter(string.Formatter):
    def get_field(self, field_name, args, kwargs):
        if field_name not in kwargs:  # no attribute or index access
            raise KeyError(field_name)
        return kwargs[field_name], field_name


PLACEHOLDER_HELP = (
    "{nr}  laufende Nummer (z. B. {nr:03} → 001)\n"
    "{datum}  heutiges Datum (z. B. {datum:%d.%m.%y})\n"
    "{zeit}  Uhrzeit (z. B. {zeit:%H:%M:%S})"
)


def expand(text: str, counter: int, now: datetime | None = None) -> str:
    """Replace {nr}, {datum}, {zeit} placeholders; leave the text unchanged on errors."""
    if "{" not in text:
        return text
    now = now or datetime.now()
    values = {
        "nr": counter,
        "datum": _DateValue(now, "%d.%m.%Y"),
        "zeit": _DateValue(now, "%H:%M"),
        "date": _DateValue(now, "%Y-%m-%d"),
        "time": _DateValue(now, "%H:%M"),
    }
    try:
        return _Formatter().vformat(text, (), values)
    except (KeyError, ValueError, IndexError, TypeError):
        return text
