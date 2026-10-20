"""Filter for harmless Qt warnings that would otherwise clutter the console."""

from __future__ import annotations

import sys

from PySide6.QtCore import QLoggingCategory, QtMsgType, qInstallMessageHandler

IGNORED_CATEGORIES = (
    # Wayland text input reports focus mismatches on every focus change (Qt bug).
    "qt.qpa.wayland.textinput",
)
IGNORED = (
    # Wayland only allows popups to grab the mouse; Qt still asks for other windows, nothing breaks.
    "This plugin supports grabbing the mouse only for popup windows",
    # Wayland: the desktop portal refuses a second app ID registration.
    "Failed to register with host portal",
)


def _handler(kind: QtMsgType, context, message: str) -> None:
    category = getattr(context, "category", "") or ""
    if category in IGNORED_CATEGORIES or any(message.startswith(text) for text in IGNORED):
        return
    prefix = f"{category}: " if category and category != "default" else ""
    sys.stderr.write(f"{prefix}{message}\n")


def install() -> None:
    qInstallMessageHandler(_handler)
    # also switch the noisy categories off at the source
    QLoggingCategory.setFilterRules("\n".join(f"{c}=false" for c in IGNORED_CATEGORIES))
