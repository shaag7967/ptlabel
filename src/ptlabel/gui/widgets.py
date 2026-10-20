"""Small reusable widgets."""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QComboBox, QCompleter, QDoubleSpinBox, QFrame, QLabel, QPushButton, QScrollArea,
                               QSizePolicy, QWidget)

from .. import fonts
from .fontui import add_font_previews
from .qtutil import fmt


class NumberSpin(QDoubleSpinBox):
    """Spin box that shows 12 instead of 12,00 but still accepts two decimals."""

    def __init__(self, lo: float, hi: float, step: float, decimals: int = 2, suffix: str = ""):
        super().__init__()
        self.setDecimals(decimals)
        self.setRange(lo, hi)
        self.setSingleStep(step)
        if suffix:
            self.setSuffix(suffix)
        self.setAccelerated(True)

    def textFromValue(self, value: float) -> str:
        return fmt(value).replace(".", self.locale().decimalPoint())

    def set_quietly(self, value: float) -> None:
        if self.value() != value and not self.hasFocus():
            with QSignalBlocker(self):
                self.setValue(value)


class FontComboBox(QComboBox):
    """Editable list of the registered font families, each shown in its own typeface."""

    def __init__(self):
        super().__init__()
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(14)
        self.reload()

    def reload(self) -> None:
        families = fonts.REGISTRY.families()
        current = self.currentText()
        with QSignalBlocker(self):
            self.clear()
            self.addItems(families)
            completer = QCompleter(families, self)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            self.setCompleter(completer)
            add_font_previews(self)
            self.setCurrentText(current)

    def set_family(self, family: str) -> None:
        if self.currentText() != family and not (self.lineEdit() and self.lineEdit().hasFocus()):
            with QSignalBlocker(self):
                self.setCurrentText(family)


def section_label(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setObjectName("section")
    return label


class PrintButton(QPushButton):
    """Prominent print button that shows what the printer is doing and is locked meanwhile."""

    def __init__(self, printer, text: str, icon=None):
        super().__init__(text)
        self.printer, self.idle_text = printer, text
        self.setObjectName("primary")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if icon is not None:
            self.setIcon(icon)
        self._dots = 0
        self._timer = QTimer(self, interval=450)
        self._timer.timeout.connect(self._animate)
        printer.status_changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        activity = self.printer.activity
        self.setEnabled(activity is None)
        if activity is None:
            self._timer.stop()
            self.setText(self.idle_text)
        else:
            if not self._timer.isActive():
                self._dots = 1
                self._timer.start()
            self._show(activity)

    def _animate(self) -> None:
        activity = self.printer.activity
        if activity is None:
            self.refresh()
            return
        self._dots = self._dots % 3 + 1
        self._show(activity)

    def _show(self, activity: str) -> None:
        self.setText(activity.rstrip(" …") + " " + "." * self._dots + " " * (3 - self._dots))


def primary_button(text: str, icon=None) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName("primary")
    if icon is not None:
        button.setIcon(icon)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


def card() -> QFrame:
    frame = QFrame()
    frame.setObjectName("card")
    return frame


def scrolling(widget: QWidget) -> QScrollArea:
    """Vertically scrollable dock content that never needs a horizontal scroll bar."""
    area = QScrollArea()
    area.setWidget(widget)
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setMinimumWidth(widget.sizeHint().width() + 16)
    return area


class StatusDot(QWidget):
    """Colored round indicator, e.g. for the printer state."""

    def __init__(self, diameter: int = 10):
        super().__init__()
        self._color = QColor("#9aa1ab")
        self._diameter = diameter
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:
        return QSize(self._diameter + 4, self._diameter + 4)

    def set_color(self, color: QColor) -> None:
        self._color = QColor(color)
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._color)
        d = self._diameter
        p.drawEllipse((self.width() - d) / 2, (self.height() - d) / 2, d, d)


class ColorSwatch(QWidget):
    """Small rounded rectangle in tape color with a stripe in ink color."""

    def __init__(self):
        super().__init__()
        self._tape = self._ink = None
        self.setFixedSize(26, 14)

    def set_colors(self, tape: str | None, ink: str | None) -> None:
        self._tape, self._ink = tape, ink
        self.setVisible(bool(tape))
        self.update()

    def paintEvent(self, _event) -> None:
        if not self._tape:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QColor(0, 0, 0, 60))
        p.setBrush(QColor(self._tape))
        p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 3, 3)
        if self._ink:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(self._ink))
            p.drawRect(6, 6, self.width() - 12, 2)
