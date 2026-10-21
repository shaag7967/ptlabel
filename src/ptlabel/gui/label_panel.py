"""Dock content for the label type, the tape and the label size."""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QLabel, QVBoxLayout, QWidget

from ..i18n import tr
from ..model import CABLE_FLAG
from ..tapes import TAPES
from .document import DocumentController
from .icons import icon
from .qtutil import fmt, set_tone
from .widgets import NumberSpin, section_label

LAYOUTS = [("normal", tr("Label"), "tag"), (CABLE_FLAG, tr("Cable flag"), "cable")]


class CableSettings(QWidget):
    """Cable diameter and fold marks of a cable flag."""

    def __init__(self, document: DocumentController):
        super().__init__()
        self.document = document
        self.diameter = NumberSpin(1, 60, 0.5, suffix=" mm")
        self.diameter.setToolTip(tr("Outer diameter of the cable; it sets the length wrapped around it"))
        self.wrap = QLabel()
        set_tone(self.wrap, "info")
        self.fold_marks = QCheckBox(tr("Fold marks"))
        self.fold_marks.setToolTip(tr("Short marks where the tape is folded around the cable"))
        hint = QLabel(tr("The tape is wrapped around the cable and the two flags are stuck back to back, "
                         "so the label reads the same from both sides."))
        hint.setWordWrap(True)
        set_tone(hint, "info")
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        form.addRow(tr("Cable diameter"), self.diameter)
        form.addRow(self.wrap)
        form.addRow(self.fold_marks)
        form.addRow(hint)
        self.diameter.valueChanged.connect(lambda v: document.set_label(cable_diameter_mm=v))
        self.fold_marks.toggled.connect(lambda on: document.set_label(fold_marks=on))

    def refresh(self) -> None:
        doc = self.document.doc
        self.diameter.set_quietly(doc.cable_diameter_mm)
        with QSignalBlocker(self.fold_marks):
            self.fold_marks.setChecked(doc.fold_marks)
        self.wrap.setText(tr("Around the cable: {length} mm").format(length=fmt(round(doc.wrap_mm, 1))))


class LabelPanel(QWidget):
    def __init__(self, document: DocumentController):
        super().__init__()
        self.document = document
        self.layout_box = QComboBox()
        for value, text, name in LAYOUTS:
            self.layout_box.addItem(icon(name), text, value)
        self.cable = CableSettings(document)
        self.tape = QComboBox()
        for tape in TAPES:
            self.tape.addItem(tape.label, tape.width_mm)
        self.print_area = QLabel()
        set_tone(self.print_area, "info")
        self.auto_length = QCheckBox()
        self.length_label = QLabel()
        self.length = NumberSpin(5, 1000, 1, suffix=" mm")
        self.margin = NumberSpin(1, 50, 0.5, suffix=" mm")
        self.margin.setToolTip(tr("Space before and after the content; objects move along"))

        column = QVBoxLayout(self)
        column.setContentsMargins(10, 8, 10, 10)
        column.addWidget(section_label(tr("Label type")))
        column.addWidget(self.layout_box)
        column.addWidget(self.cable)
        column.addWidget(section_label(tr("Tape")))
        form = QFormLayout()
        form.addRow(tr("Tape width"), self.tape)
        form.addRow(self.print_area)
        column.addLayout(form)
        column.addWidget(section_label(tr("Length")))
        form = QFormLayout()
        form.addRow(self.auto_length)
        form.addRow(self.length_label, self.length)
        form.addRow(tr("Margin left/right"), self.margin)
        column.addLayout(form)
        column.addStretch(1)

        self.layout_box.currentIndexChanged.connect(
            lambda: document.set_label(layout=self.layout_box.currentData()))
        self.tape.currentIndexChanged.connect(lambda: document.set_label(tape_mm=self.tape.currentData()))
        self.auto_length.toggled.connect(lambda on: document.set_label(auto_length=on))
        self.length.valueChanged.connect(lambda v: document.set_label(length_mm=v))
        self.margin.valueChanged.connect(lambda v: document.set_label(margin_mm=v))
        document.reset.connect(self.refresh)
        document.changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        doc = self.document.doc
        for box, value in ((self.layout_box, doc.layout), (self.tape, None)):
            with QSignalBlocker(box):
                if value is not None:
                    box.setCurrentIndex(max(0, box.findData(value)))
                else:
                    box.setCurrentIndex(max(0, box.findText(doc.tape.label)))
        self.cable.setVisible(doc.is_cable_flag)
        self.cable.refresh()
        flag = doc.is_cable_flag
        self.auto_length.setText(tr("Automatic flag length") if flag else tr("Automatic length"))
        self.length_label.setText(tr("Flag length") if flag else tr("Length"))
        with QSignalBlocker(self.auto_length):
            self.auto_length.setChecked(doc.auto_length)
        self.length.set_quietly(doc.length_mm)
        self.margin.set_quietly(doc.margin_mm)
        self.length.setEnabled(not doc.auto_length)
        self.print_area.setText(tr("Printable area: {height:.1f} mm high").format(height=doc.tape.print_mm))
