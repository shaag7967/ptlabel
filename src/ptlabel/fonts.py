"""Discovery of TrueType/OpenType fonts.

Fonts come from the system font folders, the fonts shipped with PT-Label and the
user font folder (fonts added in the GUI or downloaded from Google Fonts).
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

from . import config

FONT_EXTENSIONS = {".ttf", ".otf", ".ttc", ".otc"}
PREFERRED_DEFAULTS = ["Arial", "DejaVu Sans", "Liberation Sans", "Noto Sans", "Helvetica",
                      "FreeSans", "Ubuntu", "Cantarell"]
STANDARD_STYLES = {"regular", "normal", "book", "roman", "bold", "italic", "oblique",
                   "bold italic", "bold oblique"}
SPECIAL_WEIGHTS = ("semi", "demi", "light", "thin", "narrow", "condensed", "black", "medium",
                   "extra", "ultra", "heavy", "hairline")


BUNDLED_FONT_DIR = Path(__file__).parent / "data" / "fonts"


def user_font_dir() -> Path:
    return config.data_dir() / "fonts"


def system_font_dirs() -> list[Path]:
    if sys.platform == "win32":
        dirs = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"]
        if os.environ.get("LOCALAPPDATA"):
            dirs.append(Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "Windows" / "Fonts")
    elif sys.platform == "darwin":
        dirs = [Path("/System/Library/Fonts"), Path("/Library/Fonts"), Path.home() / "Library" / "Fonts"]
    else:
        data_home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
        dirs = [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), data_home / "fonts",
                Path.home() / ".fonts"]
    return dirs


def font_dirs() -> list[Path]:
    dirs = [*system_font_dirs(), BUNDLED_FONT_DIR, user_font_dir()]
    return [d for d in dirs if d.is_dir()]


@dataclass(frozen=True)
class Face:
    path: str
    index: int
    family: str
    style: str

    @property
    def is_bold(self) -> bool:
        s = self.style.lower()
        return any(w in s for w in ("bold", "black", "heavy"))

    @property
    def is_italic(self) -> bool:
        s = self.style.lower()
        return "italic" in s or "oblique" in s


def _scan_file(path: str) -> list[list]:
    faces = []
    count = 16 if path.lower().endswith((".ttc", ".otc")) else 1
    for index in range(count):
        try:
            font = ImageFont.truetype(path, 12, index=index)
            family, style = font.getname()
        except Exception:
            break
        if family:
            faces.append([index, family, style or "Regular"])
    return faces


class FontRegistry:
    def __init__(self, cache_file: Path | None = None):
        self.cache_file = cache_file
        self._families: dict[str, list[Face]] = {}
        self._lookup: dict[str, str] = {}
        self._lock = threading.Lock()
        self._loaded = False

    def ensure_loaded(self) -> None:
        with self._lock:
            if not self._loaded:
                self._load()
                self._loaded = True

    def reload(self) -> None:
        """Scan the font folders again, e.g. after fonts were added."""
        with self._lock:
            self._load()
            self._loaded = True

    def _load(self) -> None:
        cache = {}
        if self.cache_file:
            try:
                cache = json.loads(self.cache_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                cache = {}
        new_cache = {}
        families: dict[str, list[Face]] = {}
        for directory in font_dirs():
            for root, _, files in os.walk(directory):
                for name in files:
                    if Path(name).suffix.lower() not in FONT_EXTENSIONS:
                        continue
                    path = os.path.join(root, name)
                    try:
                        st = os.stat(path)
                    except OSError:
                        continue
                    key = f"{st.st_mtime_ns}:{st.st_size}"
                    entry = cache.get(path)
                    if not isinstance(entry, dict) or entry.get("key") != key:
                        entry = {"key": key, "faces": _scan_file(path)}
                    new_cache[path] = entry
                    for index, family, style in entry["faces"]:
                        families.setdefault(family, []).append(Face(path, index, family, style))
        self._families = families
        self._lookup = {name.casefold(): name for name in families}
        if self.cache_file and new_cache != cache:
            try:
                self.cache_file.parent.mkdir(parents=True, exist_ok=True)
                self.cache_file.write_text(json.dumps(new_cache), encoding="utf-8")
            except OSError:
                pass

    def families(self) -> list[str]:
        self.ensure_loaded()
        return sorted(self._families, key=str.casefold)

    def find_family(self, name: str) -> str | None:
        self.ensure_loaded()
        return self._lookup.get(name.strip().casefold())

    def default_family(self) -> str:
        self.ensure_loaded()
        for name in PREFERRED_DEFAULTS:
            if name.casefold() in self._lookup:
                return self._lookup[name.casefold()]
        return next(iter(sorted(self._families)), "")

    def resolve(self, family: str, bold: bool, italic: bool) -> Face | None:
        self.ensure_loaded()
        name = self.find_family(family) if family else None
        faces = self._families.get(name or self.default_family())
        if not faces:
            return None

        def score(face: Face) -> int:
            s = face.style.lower()
            value = 4 * (face.is_bold == bold) + 4 * (face.is_italic == italic)
            value += 2 if s in STANDARD_STYLES else 0
            value -= 1 if any(w in s for w in SPECIAL_WEIGHTS) else 0
            return value

        return max(faces, key=score)


def install_font_files(paths, target: Path | None = None) -> list[str]:
    """Copy font files into the user font folder and return the families they contain.

    Files that are not readable fonts are skipped. The registry is reloaded afterwards.
    """
    target = target or user_font_dir()
    families = []
    for path in map(Path, paths):
        faces = _scan_file(str(path)) if path.suffix.lower() in FONT_EXTENSIONS else []
        if not faces:
            continue
        target.mkdir(parents=True, exist_ok=True)
        if path.resolve().parent != target.resolve():
            shutil.copy2(path, target / path.name)
        families += [family for _, family, _ in faces if family not in families]
    REGISTRY.reload()
    return families


REGISTRY = FontRegistry(config.config_dir() / "fontcache.json")


@lru_cache(maxsize=256)
def _load(path: str, index: int, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size, index=index)


def get_font(family: str, size_px: int, bold: bool = False, italic: bool = False):
    """Return (font, needs_faux_bold)."""
    size_px = max(1, int(size_px))
    face = REGISTRY.resolve(family, bold, italic)
    if face is not None:
        try:
            return _load(face.path, face.index, size_px), bold and not face.is_bold
        except OSError:
            pass
    return ImageFont.load_default(size_px), bold
