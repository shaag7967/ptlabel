"""Interactive label preview: ruler, selection, hover, dragging, resizing and snapping."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPalette, QPen
from PySide6.QtWidgets import QScrollArea, QWidget

from ..model import FrameObject, LabelObject, TextObject
from ..tapes import DPI, MM_PER_INCH
from .document import DocumentController
from .preview import preview
from .qtutil import pil_to_qimage, rgb
from .snapping import Guide, snap

RULER_H = 22
PAD = 28
HANDLE = 9
SNAP_PX = 6  # screen pixels
GUIDE_COLOR = "#ff3d9a"
MAX_ZOOM = 12


class LabelCanvas(QWidget):
    zoom_changed = Signal()
    context_menu_requested = Signal(QPoint)
    edit_text_requested = Signal()

    def __init__(self, document: DocumentController, theme):
        super().__init__()
        self.document = document
        self.theme = theme
        self.zoom = 0  # 0 = automatic
        self.snapping = True
        self.tape_rgb, self.ink_rgb = (255, 255, 255), (17, 17, 17)
        self._image: QImage | None = None
        self._hover: LabelObject | None = None
        self._drag: dict | None = None
        self._guides: list[Guide] = []
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)

        self.scroll = QScrollArea()
        self.scroll.setWidget(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        document.rendered.connect(self._on_rendered)
        document.selection_changed.connect(self.update)
        document.reset.connect(self._forget_hover)
        theme.changed.connect(self.update)

    # ------------------------------------------------------------------ view settings

    def effective_zoom(self) -> float:
        """Screen pixels per print dot. Manual zoom uses whole steps, the automatic one quarter steps
        so that the label fills the visible area."""
        if self.zoom > 0:
            return self.zoom
        tape_px = round(self.document.doc.tape.width_mm * DPI / MM_PER_INCH)
        zoom = max(1, min(10, round(260 / tape_px)))
        if self._image is not None:
            viewport = self.scroll.viewport()
            fit_w = (viewport.width() - 2 * PAD) / max(1, self._image.width())
            fit_h = (viewport.height() - RULER_H - 2 * PAD) / max(1, self._image.height())
            zoom = min(zoom, fit_w, fit_h)
        return max(1.0, int(zoom * 4) / 4)

    def set_zoom(self, zoom: int) -> None:
        self.zoom = 0 if zoom <= 0 else min(MAX_ZOOM, zoom)
        self._update_size()
        self.update()
        self.zoom_changed.emit()

    def zoom_by(self, steps: int) -> None:
        zoom = self.effective_zoom()
        whole = int(zoom) if steps > 0 or zoom == int(zoom) else int(zoom) + 1  # next whole step
        self.set_zoom(max(1, whole + steps))

    def set_tape_colors(self, tape_hex: str | None, ink_hex: str | None) -> None:
        colors = rgb(tape_hex or "#ffffff"), rgb(ink_hex or "#111111")
        if colors != (self.tape_rgb, self.ink_rgb):
            self.tape_rgb, self.ink_rgb = colors
            self._on_rendered()

    def _on_rendered(self) -> None:
        result = self.document.result
        if result is not None:
            self._image = pil_to_qimage(preview(result, self.tape_rgb, self.ink_rgb))
            self._update_size()
            if self.zoom == 0:
                self.zoom_changed.emit()
        self.update()

    def _update_size(self) -> None:
        if self._image is not None:
            z = self.effective_zoom()
            self.setMinimumSize(round(2 * PAD + self._image.width() * z),
                                round(RULER_H + 2 * PAD + self._image.height() * z))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.zoom == 0:
            self._update_size()
            self.zoom_changed.emit()

    def _forget_hover(self) -> None:
        self._hover = None
        self._drag = None

    # ------------------------------------------------------------------ coordinates

    def origin(self) -> tuple[int, int]:
        height = self._image.height() * self.effective_zoom() if self._image else 0
        return PAD, max(RULER_H + PAD, round((self.height() - height) / 2))

    def to_screen(self, box) -> QRectF:
        z = self.effective_zoom()
        ox, oy = self.origin()
        return QRectF(ox + box[0] * z, oy + box[1] * z, (box[2] - box[0]) * z, (box[3] - box[1]) * z)

    def to_label(self, pos: QPointF) -> tuple[float, float]:
        ox, oy = self.origin()
        z = self.effective_zoom()
        return (pos.x() - ox) / z, (pos.y() - oy) / z

    def hit(self, px: float, py: float) -> LabelObject | None:
        """Smallest object under the cursor; empty frames only react to their outline."""
        result = self.document.result
        if result is None:
            return None
        z = self.effective_zoom()
        tolerance = 3 / z
        best = None
        for placed in reversed(result.placed):
            x0, y0, x1, y1 = placed.box
            if not (x0 - tolerance <= px <= x1 + tolerance and y0 - tolerance <= py <= y1 + tolerance):
                continue
            obj = placed.obj
            if isinstance(obj, FrameObject) and not obj.fill:
                edge = obj.thickness * result.scale + 4 / z
                if min(px - x0, x1 - px, py - y0, y1 - py) > edge:
                    continue
            area = (x1 - x0) * (y1 - y0)
            if best is None or area < best[0]:
                best = (area, obj)
        return best[1] if best else None

    def _on_handle(self, px: float, py: float) -> bool:
        placed = self.document.placed_of(self.document.selected)
        grip = (HANDLE / 2 + 2) / self.effective_zoom()
        return bool(placed) and abs(px - placed.box[2]) <= grip and abs(py - placed.box[3]) <= grip

    # ------------------------------------------------------------------ painting

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), self.theme.canvas_background)
        if self._image is None or self.document.result is None:
            return
        z = self.effective_zoom()
        ox, oy = self.origin()
        target = QRect(ox, oy, round(self._image.width() * z), round(self._image.height() * z))
        for spread, alpha in ((6, 18), (4, 28), (2, 40)):  # soft shadow
            p.fillRect(target.adjusted(-spread // 2, -spread // 2 + 2, spread // 2, spread), QColor(0, 0, 0, alpha))
        p.drawImage(target, self._image)  # no smoothing: one block per print dot
        self._paint_ruler(p, target)
        self._paint_overlays(p)
        p.end()

    def _paint_ruler(self, p: QPainter, target: QRect) -> None:
        result, z = self.document.result, self.effective_zoom()
        palette = self.palette()
        y0, y1 = target.top() - RULER_H - 6, target.top() - 6
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(palette.color(QPalette.ColorRole.Base))
        p.drawRoundedRect(QRectF(target.left(), y0, target.width(), RULER_H), 4, 4)
        font = QFont(self.font())
        font.setPointSizeF(max(6.5, font.pointSizeF() * 0.78))
        p.setFont(font)
        tick_color = palette.color(QPalette.ColorRole.PlaceholderText)
        text_color = palette.color(QPalette.ColorRole.Text)
        px_per_mm = result.scale * z
        step = 1 if px_per_mm >= 5 else 5
        for mm in range(0, int(result.length_mm) + 1, step):
            x = round(target.left() + mm * px_per_mm)
            tick = 9 if mm % 10 == 0 else 6 if mm % 5 == 0 else 3
            p.setPen(tick_color)
            p.drawLine(x, y1 - tick, x, y1 - 1)
            if mm % 10 == 0:
                p.setPen(text_color)
                p.drawText(QRect(x + 3, y0 + 2, 40, RULER_H - 8),
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, str(mm))

    def _paint_overlays(self, p: QPainter) -> None:
        document = self.document
        accent = self.palette().color(QPalette.ColorRole.Highlight)
        p.setBrush(Qt.BrushStyle.NoBrush)
        hover = document.placed_of(self._hover)
        if hover and self._hover is not document.selected and self._drag is None:
            color = QColor(accent)
            color.setAlpha(140)
            p.setPen(QPen(color, 1))
            p.drawRect(self.to_screen(hover.box).adjusted(-1, -1, 0, 0))
        selected = document.placed_of(document.selected)
        if selected:
            rect = self.to_screen(selected.box).adjusted(-1, -1, 0, 0)
            pen = QPen(accent, 1, Qt.PenStyle.CustomDashLine)
            pen.setDashPattern([4, 3])
            p.setPen(pen)
            p.drawRect(rect)
            r = HANDLE / 2
            corner = rect.bottomRight()
            p.setPen(QPen(accent, 1.5))
            p.setBrush(QColor("white"))
            p.drawRoundedRect(QRectF(corner.x() - r, corner.y() - r, 2 * r, 2 * r), 2, 2)
        if self._guides and document.result:
            p.setPen(QPen(QColor(GUIDE_COLOR), 1))
            label = self.to_screen((0, 0, *document.result.image.size))
            for guide in self._guides:
                if guide.vertical:
                    x = self.to_screen((guide.position, 0, guide.position, 0)).left()
                    p.drawLine(QPointF(x, label.top() - 4), QPointF(x, label.bottom() + 4))
                else:
                    y = self.to_screen((0, guide.position, 0, guide.position)).top()
                    p.drawLine(QPointF(label.left() - 4, y), QPointF(label.right() + 4, y))

    # ------------------------------------------------------------------ mouse

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self.document.result is None:
            return
        self.setFocus()
        document = self.document
        px, py = self.to_label(event.position())
        if self._on_handle(px, py):
            obj = document.selected
            placed = document.placed_of(obj)
            if isinstance(obj, TextObject):
                document.freeze_auto_text(obj)
            size = (max(1, placed.box[2] - placed.box[0]), max(1, placed.box[3] - placed.box[1]))
            self._drag = {"mode": "resize", "obj": obj, "start": (px, py), "orig": obj.copy(), "size": size,
                          "moved": False}
            return
        hit = self.hit(px, py)
        document.select(hit)
        if hit is not None:
            placed = document.placed_of(hit)
            others = [p.box for p in document.result.placed if p.obj is not hit]
            x_now = placed.box[0] / document.result.scale  # differs from x for anchored objects
            self._drag = {"mode": "move", "obj": hit, "start": (px, py), "orig": (x_now, hit.y),
                          "box": placed.box, "others": others, "moved": False}

    def mouseMoveEvent(self, event) -> None:
        px, py = self.to_label(event.position())
        if not (event.buttons() & Qt.MouseButton.LeftButton) or self._drag is None:
            self._update_hover(px, py)
            return
        drag, z = self._drag, self.effective_zoom()
        dx, dy = px - drag["start"][0], py - drag["start"][1]
        if not drag["moved"] and abs(dx) * z < 3 and abs(dy) * z < 3:
            return
        drag["moved"] = True
        free = bool(event.modifiers() & Qt.KeyboardModifier.AltModifier)
        if drag["mode"] == "move":
            self._move(drag, dx, dy, snapping=self.snapping and not free)
        else:
            self._resize(drag, dx, dy)
        self.document.edited(record=False)

    def _move(self, drag: dict, dx: float, dy: float, snapping: bool) -> None:
        obj, result = drag["obj"], self.document.result
        fixed_y = isinstance(obj, TextObject) and obj.auto_size
        self._guides = []
        if snapping:
            x0, y0, x1, y1 = drag["box"]
            moved = (x0 + dx, y0 + dy, x1 + dx, y1 + dy) if not fixed_y else (x0 + dx, y0, x1 + dx, y1)
            sx, sy, self._guides = snap(moved, result, drag["others"], SNAP_PX / self.effective_zoom(),
                                        snap_y=not fixed_y)
            dx, dy = dx + sx, dy + sy
        if obj.h_align != "free" and abs(dx) * self.effective_zoom() >= 3:
            obj.h_align = "free"  # dragged sideways: no longer centered / right-aligned
        if obj.h_align == "free":
            obj.x = round(drag["orig"][0] + dx / result.scale, 1 if not snapping else 2)
        if not fixed_y:
            obj.y = round(drag["orig"][1] + dy / result.scale, 1 if not snapping else 2)

    def _resize(self, drag: dict, dx: float, dy: float) -> None:
        obj = drag["obj"]
        w0, h0 = drag["size"]
        fx, fy = max(1.0, w0 + dx) / w0, max(1.0, h0 + dy) / h0
        if obj.rotation % 180:
            fx, fy = fy, fx
        obj.resize(drag["orig"], fx, fy)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        drag, self._drag = self._drag, None
        self._guides = []
        if drag and drag["moved"]:
            self.document.edited(commit=True)
        self.update()

    def _update_hover(self, px: float, py: float) -> None:
        if self._on_handle(px, py):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            hover = self.document.selected
        else:
            hover = self.hit(px, py)
            self.setCursor(Qt.CursorShape.SizeAllCursor if hover else Qt.CursorShape.ArrowCursor)
        if hover is not self._hover:
            self._hover = hover
            self.update()

    def leaveEvent(self, _event) -> None:
        if self._hover is not None:
            self._hover = None
            self.update()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.document.selected is not None:
            self.edit_text_requested.emit()

    def contextMenuEvent(self, event) -> None:
        hit = self.hit(*self.to_label(QPointF(event.pos())))
        if hit is not None:
            self.document.select(hit)
            self.context_menu_requested.emit(event.globalPos())

    # ------------------------------------------------------------------ keyboard and wheel

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.document.delete_selected()
            return
        arrows = {Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0), Qt.Key.Key_Up: (0, -1), Qt.Key.Key_Down: (0, 1)}
        if key in arrows:
            step = 0.1 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 0.5
            dx, dy = arrows[key]
            self.document.nudge(dx * step, dy * step)
            return
        super().keyPressEvent(event)

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta()
        amount = delta.y() or delta.x()
        if not amount:
            return
        mods = event.modifiers()
        if mods & Qt.KeyboardModifier.ControlModifier:
            self.zoom_by(1 if amount > 0 else -1)
        elif mods & Qt.KeyboardModifier.ShiftModifier:
            bar = self.scroll.verticalScrollBar()
            bar.setValue(bar.value() - amount // 2)
        else:
            bar = self.scroll.horizontalScrollBar()
            bar.setValue(bar.value() - amount)
        event.accept()
