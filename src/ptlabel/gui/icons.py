"""Monochrome SVG icons (Lucide, ISC license) drawn in the text color of the current palette.

The icons are rendered when they are painted, so they follow a theme change without
being recreated.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QIconEngine, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer

ICON_DIR = Path(__file__).resolve().parent.parent / "data" / "icons"


@lru_cache(maxsize=None)
def _svg(name: str) -> bytes:
    return (ICON_DIR / f"{name}.svg").read_bytes()


@lru_cache(maxsize=512)
def _renderer(name: str, color: str) -> QSvgRenderer:
    return QSvgRenderer(QByteArray(_svg(name).replace(b"currentColor", color.encode())))


class SvgIconEngine(QIconEngine):
    def __init__(self, name: str, color: QColor | None = None):
        super().__init__()
        self.name = name
        self.color = color

    def _color(self, mode: QIcon.Mode) -> QColor:
        palette = QGuiApplication.palette()
        if mode == QIcon.Mode.Disabled:
            return palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText)
        if mode == QIcon.Mode.Selected:
            return palette.color(QPalette.ColorRole.HighlightedText)
        return self.color or palette.color(QPalette.ColorRole.WindowText)

    def paint(self, painter: QPainter, rect: QRect, mode: QIcon.Mode, state: QIcon.State) -> None:
        _renderer(self.name, self._color(mode).name()).render(painter, QRectF(rect))

    def scaledPixmap(self, size: QSize, mode: QIcon.Mode, state: QIcon.State, scale: float) -> QPixmap:
        pixmap = QPixmap(size * scale)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        self.paint(painter, QRect(QPoint(0, 0), pixmap.size()), mode, state)
        painter.end()
        pixmap.setDevicePixelRatio(scale)
        return pixmap

    def pixmap(self, size: QSize, mode: QIcon.Mode, state: QIcon.State) -> QPixmap:
        return self.scaledPixmap(size, mode, state, 1.0)

    def clone(self) -> QIconEngine:
        return SvgIconEngine(self.name, self.color)


def icon(name: str, color: QColor | str | None = None) -> QIcon:
    return QIcon(SvgIconEngine(name, QColor(color) if color else None))
