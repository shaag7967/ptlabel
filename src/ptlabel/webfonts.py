"""Google Fonts via the Fontsource API (https://fontsource.org), no API key needed.

Fonts are downloaded as static TTF files of the "latin" subset (covers Western European
languages including German umlauts and €), regular and bold, upright and italic if available.
"""

from __future__ import annotations

import json
import re
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import __version__, config, fonts
from .i18n import tr

API = "https://api.fontsource.org/v1/fonts"
SUBSET = "latin"
LIST_MAX_AGE = 7 * 24 * 3600
TIMEOUT = 20


@dataclass(frozen=True)
class WebFont:
    id: str
    family: str
    category: str
    weights: tuple[int, ...]
    styles: tuple[str, ...]
    license: str


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": f"ptlabel/{__version__}"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read()


def _list_cache() -> Path:
    return config.cache_dir() / "webfonts.json"


def list_fonts(refresh: bool = False) -> list[WebFont]:
    """All Google fonts that have a latin subset, sorted by family (cached for a week)."""
    cache = _list_cache()
    raw = None
    if not refresh:
        try:
            if time.time() - cache.stat().st_mtime < LIST_MAX_AGE:
                raw = json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = None
    if raw is None:
        raw = json.loads(_get(f"{API}?type=google&subsets={SUBSET}"))
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(raw), encoding="utf-8")
        except OSError:
            pass
    result = [WebFont(f["id"], f["family"], f.get("category", ""), tuple(f.get("weights", ())),
                      tuple(f.get("styles", ())), f.get("license", ""))
              for f in raw if SUBSET in f.get("subsets", ())]
    return sorted(result, key=lambda f: f.family.casefold())


def _variant_urls(font: WebFont) -> dict[tuple[int, str], str]:
    """(weight, style) -> TTF URL for the weights and styles that get installed."""
    detail = json.loads(_get(f"{API}/{font.id}"))
    variants = detail.get("variants", {})
    weights = sorted(int(w) for w in variants)
    if not weights:
        return {}
    regular = min(weights, key=lambda w: abs(w - 400))
    wanted = [regular] + ([700] if 700 in weights and regular != 700 else [])
    urls = {}
    for weight in wanted:
        for style, subsets in variants[str(weight)].items():
            url = subsets.get(SUBSET, {}).get("url", {}).get("ttf")
            if url and style in ("normal", "italic"):
                urls[(weight, style)] = url
    return urls


def _safe(name: str) -> str:
    return re.sub(r"[^a-z0-9-]", "", name.lower())


def download_regular(font: WebFont, target: Path | None = None) -> Path:
    """Download only the regular upright file, e.g. for a preview. Returns the file path."""
    target = target or config.cache_dir() / "webfont-previews"
    path = target / f"{_safe(font.id)}.ttf"
    if not path.exists():
        urls = _variant_urls(font)
        url = next((u for (w, s), u in sorted(urls.items()) if s == "normal"), None) or next(iter(urls.values()))
        target.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_get(url))
    return path


def install(font: WebFont) -> list[str]:
    """Download the font into the user font folder; returns the installed family names."""
    urls = _variant_urls(font)
    if not urls:
        raise ValueError(tr("No downloadable files for {family}").format(family=font.family))
    folder = fonts.user_font_dir() / _safe(font.id)
    folder.mkdir(parents=True, exist_ok=True)
    files = []
    for (weight, style), url in urls.items():
        path = folder / f"{_safe(font.id)}-{weight}-{style}.ttf"
        path.write_bytes(_get(url))
        files.append(path)
    return fonts.install_font_files(files, folder)
