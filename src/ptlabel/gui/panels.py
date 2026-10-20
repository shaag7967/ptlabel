"""Side panels: label settings, print settings and the generated property editors."""

from __future__ import annotations

from PySide6.QtCore import QObject, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QCheckBox, QComboBox, QCompleter, QDoubleSpinBox, QGridLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSpinBox)

from ..model import Prop
from ..tapes import TAPES
from .qtutil import COLOR_INFO, fmt, set_color

PRINT_FLAGS = [
    ("auto_cut", "Automatisch schneiden"),
    ("half_cut", "Halbschnitt zwischen Etiketten"),
    ("chain", "Kettendruck (spart Band, letztes\nEtikett bleibt im Gerät)"),
    ("mirror", "Spiegeln"),
    ("high_res", "Hohe Auflösung 180×360 dpi"),
]


class NumberSpin(QDoubleSpinBox):
    """Spin box that shows 12 instead of 12,00 but still accepts two decimals."""

    def __init__(self, lo: float, hi: float, step: float, decimals: int = 2):
        super().__init__()
        self.setDecimals(decimals)
        self.setRange(lo, hi)
        self.setSingleStep(step)

    def textFromValue(self, value: float) -> str:
        return fmt(value).replace(".", self.locale().decimalPoint())


def print_button() -> QPushButton:
    button = QPushButton("Drucken")
    font = QFont(button.font())
    font.setBold(True)
    button.setFont(font)
    button.setMinimumHeight(32)
    return button


class LabelPanel(QGroupBox):
    def __init__(self):
        super().__init__("Etikett")
        grid = QGridLayout(self)
        grid.setColumnStretch(1, 1)
        self.tape = QComboBox()
        self.tape.addItems([t.label for t in TAPES])
        self.print_area = QLabel()
        set_color(self.print_area, COLOR_INFO)
        self.auto_length = QCheckBox("Länge automatisch")
        self.length = NumberSpin(5, 1000, 1)
        self.margin = NumberSpin(1, 50, 0.5)
        grid.addWidget(QLabel("Bandbreite"), 0, 0)
        grid.addWidget(self.tape, 0, 1)
        grid.addWidget(self.print_area, 1, 0, 1, 2)
        grid.addWidget(self.auto_length, 2, 0, 1, 2)
        grid.addWidget(QLabel("Länge (mm)"), 3, 0)
        grid.addWidget(self.length, 3, 1)
        grid.addWidget(QLabel("Rand links/rechts (mm)"), 4, 0)
        grid.addWidget(self.margin, 4, 1)

    def connect(self, slot) -> None:
        self.tape.currentIndexChanged.connect(slot)
        self.auto_length.toggled.connect(slot)
        self.length.valueChanged.connect(slot)
        self.margin.valueChanged.connect(slot)


class PrintPanel(QGroupBox):
    def __init__(self):
        super().__init__("Drucken")
        grid = QGridLayout(self)
        grid.setColumnStretch(1, 1)
        self.printer = QLineEdit()
        self.search = QPushButton("Suchen…")
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.copies = QSpinBox()
        self.copies.setRange(1, 999)
        self.counter = QSpinBox()
        self.counter.setRange(0, 999999)
        grid.addWidget(QLabel("Drucker"), 0, 0)
        grid.addWidget(self.printer, 0, 1)
        grid.addWidget(self.search, 0, 2)
        grid.addWidget(self.status, 1, 0, 1, 3)
        grid.setRowMinimumHeight(1, 36)
        grid.addWidget(QLabel("Kopien"), 2, 0)
        grid.addWidget(self.copies, 2, 1)
        grid.addWidget(QLabel("Nummer {nr} ab"), 3, 0)
        grid.addWidget(self.counter, 3, 1)
        self.flags: dict[str, QCheckBox] = {}
        for row, (attr, text) in enumerate(PRINT_FLAGS, start=4):
            box = QCheckBox(text)
            grid.addWidget(box, row, 0, 1, 3)
            self.flags[attr] = box
        self.print = print_button()
        grid.addWidget(self.print, len(PRINT_FLAGS) + 4, 0, 1, 3)

    def connect(self, slot) -> None:
        self.copies.valueChanged.connect(slot)
        self.counter.valueChanged.connect(slot)
        for box in self.flags.values():
            box.toggled.connect(slot)


class PropField(QObject):
    """Editor widget for one ``Prop`` of the selected object."""

    changed = Signal()

    def __init__(self, prop: Prop, value, font_families: list[str]):
        super().__init__()
        self.prop = prop
        kind = prop.kind
        if kind == "bool":
            self.widget = QCheckBox(prop.label)
            self.widget.toggled.connect(self.changed)
        elif kind in ("float", "int"):
            lo, hi, step = prop.options
            self.widget = NumberSpin(lo, hi, step, 0 if kind == "int" else 2)
            self.widget.valueChanged.connect(self.changed)
        elif kind == "choice":
            self.widget = QComboBox()
            for data, label in prop.options:
                self.widget.addItem(label, data)
            self.widget.currentIndexChanged.connect(self.changed)
        elif kind == "font":
            self.widget = QComboBox()
            self.widget.setEditable(True)
            self.widget.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            self.widget.addItems(font_families)
            completer = QCompleter(font_families, self.widget)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            self.widget.setCompleter(completer)
            self.widget.currentTextChanged.connect(self.changed)
        elif kind == "multiline":
            self.widget = QPlainTextEdit()
            self.widget.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
            line = self.widget.fontMetrics().lineSpacing()
            self.widget.setFixedHeight(line * 3 + 14)
            self.widget.textChanged.connect(self.changed)
        else:
            self.widget = QLineEdit()
            self.widget.textChanged.connect(self.changed)
        self.set_value(value)

    def value(self):
        w, kind = self.widget, self.prop.kind
        if kind == "bool":
            return w.isChecked()
        if kind in ("float", "int"):
            return w.value()
        if kind == "choice":
            return w.currentData()
        if kind == "font":
            return w.currentText()
        if kind == "multiline":
            return w.toPlainText()
        return w.text()

    def set_value(self, value) -> None:
        """Show ``value`` without emitting ``changed``."""
        w, kind = self.widget, self.prop.kind
        with QSignalBlocker(w):
            if kind == "bool":
                w.setChecked(bool(value))
            elif kind in ("float", "int"):
                w.setValue(float(value))
            elif kind == "choice":
                index = w.findData(value)
                if index >= 0:
                    w.setCurrentIndex(index)
            elif kind == "font":
                if w.currentText() != value:
                    w.setCurrentText(value)
            elif kind == "multiline":
                if w.toPlainText() != value:
                    w.setPlainText(value)
            elif w.text() != str(value):
                w.setText(str(value))


def image_row(name: str, on_load) -> QHBoxLayout:
    row = QHBoxLayout()
    button = QPushButton("Bild laden…")
    button.clicked.connect(on_load)
    label = QLabel(name or "(kein Bild)")
    set_color(label, COLOR_INFO)
    row.addWidget(button)
    row.addWidget(label, 1)
    return row
