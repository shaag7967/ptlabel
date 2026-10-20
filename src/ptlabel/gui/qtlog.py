"""Filter for harmless Qt warnings that would otherwise clutter the console."""

from __future__ import annotations

import sys

from PySide6.QtCore import QtMsgType, qInstallMessageHandler

IGNORED = (
    # Wayland only allows popups to grab the mouse; Qt still asks for other windows, nothing breaks.
    "This plugin supports grabbing the mouse only for popup windows",
    # Wayland text input reports focus mismatches on every focus change (Qt bug).
    "virtual void QtWaylandClient::QWaylandTextInputv3::disableSurface",
    # Wayland: the desktop portal refuses a second app ID registration.
    "Failed to register with host portal",
)


def _handler(kind: QtMsgType, context, message: str) -> None:
    if any(message.startswith(text) for text in IGNORED):
        return
    category = getattr(context, "category", "") or ""
    prefix = f"{category}: " if category and category != "default" else ""
    sys.stderr.write(f"{prefix}{message}\n")


def install() -> None:
    qInstallMessageHandler(_handler)
