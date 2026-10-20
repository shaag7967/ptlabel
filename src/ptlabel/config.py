"""Per-user settings (printer address, window geometry, ...)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

DEFAULTS = {
    "printer": "",
    "geometry": "",
    "zoom": 0,
    "last_dir": "",
}


def config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "ptlabel"


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
