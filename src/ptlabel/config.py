"""Per-user settings (printer address, window geometry, ...)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

DEFAULTS = {
    "printer": "",
    "window_geometry": "",
    "window_state": "",
    "theme": "system",
    "snapping": True,
    "recent": [],
    "zoom": 0,
    "last_dir": "",
    "language": "",  # empty: follow the system
}


def config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "ptlabel"


def data_dir() -> Path:
    """Per-user data such as installed fonts."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "ptlabel"


def cache_dir() -> Path:
    """Files that can be downloaded again, e.g. font previews."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "ptlabel" / "cache"
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "ptlabel"


def load() -> dict:
    data = dict(DEFAULTS)
    try:
        data.update(json.loads((config_dir() / "config.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return data


def save(data: dict) -> None:
    try:
        config_dir().mkdir(parents=True, exist_ok=True)
        (config_dir() / "config.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass
