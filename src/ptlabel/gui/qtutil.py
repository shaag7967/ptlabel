"""Shared constants and small Qt helpers for the user interface."""

from __future__ import annotations

import threading

from PIL import Image, ImageDraw
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import QWidget

APP_NAME = "PT-Label"
STATUS_INTERVAL_MS = 20000
MAX_IMAGE_PX = 1200

# Semantic text colors, styled in theme.py
TONES = ("info", "ok", "warn", "error", "busy")


def fmt(value: float) -> str:
    return f"{round(float(value), 2):g}"


def rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def index_of(items: list, obj) -> int | None:
    """Index by identity (dataclass equality would confuse identical copies)."""
    return next((i for i, item in enumerate(items) if item is obj), None)


def set_tone(widget: QWidget, tone: str) -> None:
    """Color a label by meaning; the colors come from the style sheet of the theme."""
    if widget.property("tone") != tone:
        widget.setProperty("tone", tone)
        widget.style().unpolish(widget)
        widget.style().polish(widget)


def pil_to_qimage(img: Image.Image) -> QImage:
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    return QImage(data, img.width, img.height, img.width * 4, QImage.Format.Format_RGBA8888).copy()


def app_icon() -> QIcon:
    icon = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(icon)
    draw.rounded_rectangle((2, 16, 61, 47), radius=6, fill=(248, 214, 22), outline=(60, 60, 60), width=2)
    draw.rectangle((12, 26, 50, 29), fill=(20, 20, 20))
    draw.rectangle((12, 34, 40, 37), fill=(20, 20, 20))
    return QIcon(QPixmap.fromImage(pil_to_qimage(icon)))


class BackgroundRunner(QObject):
    """Runs blocking work in a thread; ``done(result, error)`` is called in the GUI thread."""

    _finished = Signal(object, object, object)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._finished.connect(self._dispatch)  # queued across threads

    def run(self, work, done=None) -> None:
        def worker():
            try:
                result, error = work(), None
            except Exception as exc:
                result, error = None, exc
            self._finished.emit(done, result, error)

        threading.Thread(target=worker, daemon=True).start()

    @staticmethod
    def _dispatch(done, result, error) -> None:
        if done:
            done(result, error)
