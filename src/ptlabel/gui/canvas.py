"""Label preview with ruler and selection; forwards mouse and keyboard input to the main window."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QScrollArea, QWidget

from ..render import RenderResult
from .qtutil import ACCENT, CANVAS_BG, HANDLE, PAD, RULER_H

if TYPE_CHECKING:
    from .window import MainWindow


class LabelCanvas(QWidget):
    def __init__(self, app: MainWindow):
        super().__init__()
        self.app = app
        self.image: QImage | None = None  # unscaled preview, one pixel per print dot
        self.result: RenderResult | None = None
        self.zoom = 1
        self.selection: tuple[int, int, int, int] | None = None  # pixel box in the rendered image
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)

        self.scroll = QScrollArea()
        self.scroll.setWidget(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet(f"QScrollArea {{ background: {CANVAS_BG}; border: none; }}")

    def set_image(self, image: QImage, result: RenderResult, zoom: int) -> None:
        self.image, self.result, self.zoom = image, result, zoom
        self.setMinimumSize(2 * PAD + image.width() * zoom, RULER_H + 2 * PAD + image.height() * zoom)
        self.update()

    def set_selection(self, box) -> None:
        if box != self.selection:
            self.selection = box
            self.update()

    # ------------------------------------------------------------------ geometry

    def origin(self) -> tuple[int, int]:
        height = self.image.height() * self.zoom if self.image else 0
        return PAD, max(RULER_H + PAD, (self.height() - height) // 2)

    def to_screen(self, box) -> QRectF:
        z = self.zoom
        ox, oy = self.origin()
        return QRectF(ox + box[0] * z, oy + box[1] * z, (box[2] - box[0]) * z, (box[3] - box[1]) * z)

    def to_label(self, pos: QPointF) -> tuple[float, float]:
        ox, oy = self.origin()
        return (pos.x() - ox) / self.zoom, (pos.y() - oy) / self.zoom

    # ------------------------------------------------------------------ painting

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(CANVAS_BG))
        if self.image is None or self.result is None:
            return
        z = self.zoom
        ox, oy = self.origin()
        target = QRect(ox, oy, self.image.width() * z, self.image.height() * z)
        p.fillRect(target.translated(4, 4), QColor("#5c626a"))
        p.drawImage(target, self.image)  # no smoothing: nearest neighbour like the printer
        self._paint_ruler(p, target.width())
        if self.selection is not None:
            self._paint_selection(p)
        p.end()

    def _paint_ruler(self, p: QPainter, width: int) -> None:
        res, z = self.result, self.zoom
        ox, oy = self.origin()
        y0, y1 = oy - RULER_H - 4, oy - 4
        p.setPen(QColor("#c5c9ce"))
        p.setBrush(QColor("#eef0f2"))
        p.drawRect(ox, y0, width, RULER_H)
        font = QFont(self.font())
        font.setPointSizeF(max(6.0, font.pointSizeF() * 0.8))
        p.setFont(font)
        px_per_mm = res.scale * z
        step = 1 if px_per_mm >= 5 else 5
        for mm in range(0, int(res.length_mm) + 1, step):
            x = round(ox + mm * px_per_mm)
            tick = 10 if mm % 10 == 0 else 6 if mm % 5 == 0 else 3
            p.setPen(QColor("#555555"))
            p.drawLine(x, y1 - tick, x, y1)
            if mm % 10 == 0:
                p.setPen(QColor("#333333"))
                p.drawText(QRect(x + 3, y0 + 1, 40, RULER_H - 10),
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, str(mm))

    def _paint_selection(self, p: QPainter) -> None:
        rect = self.to_screen(self.selection).adjusted(-1, -1, 0, 0)
        pen = QPen(QColor(ACCENT), 1, Qt.PenStyle.CustomDashLine)
        pen.setDashPattern([4, 2])
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(rect)
        r = HANDLE // 2
        corner = rect.bottomRight()
        p.setPen(QColor(ACCENT))
        p.setBrush(QColor("white"))
        p.drawRect(QRectF(corner.x() - r, corner.y() - r, 2 * r, 2 * r))

    # ------------------------------------------------------------------ input

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            self.app.on_press(*self.to_label(event.position()))

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.app.on_motion(*self.to_label(event.position()))

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.app.on_release()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.app.on_double()

    def contextMenuEvent(self, event) -> None:
        self.app.on_context(*self.to_label(QPointF(event.pos())), event.globalPos())

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.app.delete_selected()
            return
        arrows = {Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0), Qt.Key.Key_Up: (0, -1), Qt.Key.Key_Down: (0, 1)}
        if key in arrows:
            step = 0.1 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 0.5
            dx, dy = arrows[key]
            self.app.nudge(dx * step, dy * step)
            return
        super().keyPressEvent(event)

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta()
        amount = delta.y() or delta.x()
        if not amount:
            return
        mods = event.modifiers()
        if mods & Qt.KeyboardModifier.ControlModifier:
            self.app.set_zoom(self.app.current_zoom() + (1 if amount > 0 else -1))
        elif mods & Qt.KeyboardModifier.ShiftModifier:
            bar = self.scroll.verticalScrollBar()
            bar.setValue(bar.value() - amount // 2)
        else:
            bar = self.scroll.horizontalScrollBar()
            bar.setValue(bar.value() - amount)
        event.accept()
