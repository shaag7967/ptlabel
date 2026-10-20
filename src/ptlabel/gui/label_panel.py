"""Dock content for the tape and label size."""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QLabel, QVBoxLayout, QWidget

from ..i18n import tr
from ..tapes import TAPES
from .document import DocumentController
from .qtutil import set_tone
from .widgets import NumberSpin, section_label


class LabelPanel(QWidget):
    def __init__(self, document: DocumentController):
        super().__init__()
        self.document = document
        self.tape = QComboBox()
        for tape in TAPES:
            self.tape.addItem(tape.label, tape.width_mm)
        self.print_area = QLabel()
        set_tone(self.print_area, "info")
        self.auto_length = QCheckBox(tr("Automatic length"))
        self.length = NumberSpin(5, 1000, 1, suffix=" mm")
        self.margin = NumberSpin(1, 50, 0.5, suffix=" mm")
        self.margin.setToolTip(tr("Space before and after the content; objects move along"))

        column = QVBoxLayout(self)
        column.setContentsMargins(10, 8, 10, 10)
        column.addWidget(section_label(tr("Tape")))
        form = QFormLayout()
        form.addRow(tr("Tape width"), self.tape)
        form.addRow(self.print_area)
        column.addLayout(form)
        column.addWidget(section_label(tr("Length")))
        form = QFormLayout()
        form.addRow(self.auto_length)
        form.addRow(tr("Length"), self.length)
        form.addRow(tr("Margin left/right"), self.margin)
        column.addLayout(form)
        column.addStretch(1)

        self.tape.currentIndexChanged.connect(lambda: document.set_label(tape_mm=self.tape.currentData()))
        self.auto_length.toggled.connect(lambda on: document.set_label(auto_length=on))
        self.length.valueChanged.connect(lambda v: document.set_label(length_mm=v))
        self.margin.valueChanged.connect(lambda v: document.set_label(margin_mm=v))
        document.reset.connect(self.refresh)
        document.changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        doc = self.document.doc
        with QSignalBlocker(self.tape):
            self.tape.setCurrentIndex(max(0, self.tape.findText(doc.tape.label)))
        with QSignalBlocker(self.auto_length):
            self.auto_length.setChecked(doc.auto_length)
        self.length.set_quietly(doc.length_mm)
        self.margin.set_quietly(doc.margin_mm)
        self.length.setEnabled(not doc.auto_length)
        self.print_area.setText(tr("Printable area: {height:.1f} mm high").format(height=doc.tape.print_mm))
