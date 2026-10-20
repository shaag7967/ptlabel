"""Dock content for the printer and the print options."""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import (QCheckBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QSpinBox, QToolButton,
                               QVBoxLayout, QWidget)

from ..i18n import tr
from .document import DocumentController
from .icons import icon
from .printing import PrinterController
from .qtutil import set_tone
from .widgets import ColorSwatch, StatusDot, card, primary_button, section_label

PRINT_FLAGS = [  # attribute, label, tooltip
    ("auto_cut", tr("Cut automatically"), tr("Cut after every label")),
    ("half_cut", tr("Half cut between labels"), tr("Cut only through the tape, not the backing")),
    ("chain", tr("Chain printing"), tr("Saves tape: the last label stays in the printer until the next job")),
    ("mirror", tr("Mirror"), tr("Print mirror-inverted, e.g. for transparent tape on glass")),
    ("high_res", tr("High resolution"), tr("180×360 dpi: finer, but slower")),
]


class PrinterCard(QWidget):
    """Printer address, search button and the live status."""

    search_requested = Signal()

    def __init__(self, printer: PrinterController, theme):
        super().__init__()
        self.printer, self.theme = printer, theme
        self.address = QLineEdit(printer.target)
        self.address.setPlaceholderText(tr("Host name or IP address"))
        self.address.setClearButtonEnabled(True)
        search = QToolButton()
        search.setIcon(icon("radar"))
        search.setToolTip(tr("Search the network for Brother printers"))
        search.clicked.connect(self.search_requested)
        refresh = QToolButton()
        refresh.setIcon(icon("refresh-cw"))
        refresh.setToolTip(tr("Query status"))
        refresh.clicked.connect(lambda: printer.refresh(manual=True))

        box = card()
        layout = QVBoxLayout(box)
        row = QHBoxLayout()
        row.addWidget(self.address, 1)
        row.addWidget(search)
        row.addWidget(refresh)
        layout.addLayout(row)
        status_row = QHBoxLayout()
        self.dot = StatusDot()
        self.swatch = ColorSwatch()
        self.state = QLabel()
        self.state.setWordWrap(True)
        status_row.addWidget(self.dot)
        status_row.addWidget(self.state, 1)
        status_row.addWidget(self.swatch)
        layout.addLayout(status_row)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(box)

        self.address.editingFinished.connect(lambda: printer.set_target(self.address.text()))
        printer.status_changed.connect(self.refresh)
        theme.changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        printer = self.printer
        if self.address.text() != printer.target and not self.address.hasFocus():
            self.address.setText(printer.target)
        self.state.setText(printer.text)
        set_tone(self.state, "error" if printer.tone == "error" else "info")
        self.dot.set_color(self.theme.tone_color(printer.tone))
        status = printer.status
        self.swatch.set_colors(status.tape_color_rgb if status else None, status.text_color_rgb if status else None)


class PrintPanel(QWidget):
    print_requested = Signal()

    def __init__(self, document: DocumentController, printer: PrinterController, theme):
        super().__init__()
        self.document = document
        self.printer_card = PrinterCard(printer, theme)
        self.copies = QSpinBox()
        self.copies.setRange(1, 999)
        self.counter = QSpinBox()
        self.counter.setRange(0, 999999)
        self.counter.setToolTip(tr("Value of the {nr} placeholder on the first label"))
        self.flags = {}
        for attr, text, tip in PRINT_FLAGS:
            self.flags[attr] = QCheckBox(text)
            self.flags[attr].setToolTip(tip)
        self.print_button = primary_button(tr("Print"), icon("printer", "white"))
        self.print_button.clicked.connect(self.print_requested)

        column = QVBoxLayout(self)
        column.setContentsMargins(10, 8, 10, 10)
        column.addWidget(section_label(tr("Printer")))
        column.addWidget(self.printer_card)
        column.addWidget(section_label(tr("Copies")))
        form = QFormLayout()
        form.addRow(tr("Copies"), self.copies)
        form.addRow(tr("Start {nr} at"), self.counter)
        column.addLayout(form)
        column.addWidget(section_label(tr("Options")))
        for box in self.flags.values():
            column.addWidget(box)
        column.addSpacing(8)
        column.addWidget(self.print_button)
        column.addStretch(1)

        self.copies.valueChanged.connect(lambda v: document.set_print_options(copies=v))
        self.counter.valueChanged.connect(lambda v: document.set_print_options(counter_start=v))
        for attr, box in self.flags.items():
            box.toggled.connect(lambda on, a=attr: document.set_print_options(**{a: on}))
        document.reset.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        doc = self.document.doc
        for spin, value in ((self.copies, doc.copies), (self.counter, doc.counter_start)):
            with QSignalBlocker(spin):
                spin.setValue(value)
        for attr, box in self.flags.items():
            with QSignalBlocker(box):
                box.setChecked(bool(getattr(doc, attr)))
