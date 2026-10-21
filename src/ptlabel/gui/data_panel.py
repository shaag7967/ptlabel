"""Dock content for series printing: a CSV table whose rows fill the {column} placeholders."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QHBoxLayout, QLabel, QMenu, QTableWidget,
                               QTableWidgetItem, QToolButton, QVBoxLayout, QWidget)

from .. import merge
from ..i18n import ntr, tr
from .document import DocumentController
from .icons import icon
from .qtutil import set_tone


class DataPanel(QWidget):
    load_requested = Signal()

    def __init__(self, document: DocumentController):
        super().__init__()
        self.document = document
        load = QToolButton()
        load.setIcon(icon("sheet"))
        load.setText(tr("Load CSV file…"))
        load.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        load.clicked.connect(self.load_requested)
        self.unlink = QToolButton()
        self.unlink.setIcon(icon("x"))
        self.unlink.setToolTip(tr("Remove the data file from the label"))
        self.unlink.clicked.connect(lambda: document.set_data_file(""))
        self.insert = QToolButton()
        self.insert.setIcon(icon("braces"))
        self.insert.setText(tr("Insert field"))
        self.insert.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.insert.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.insert.setToolTip(tr("Add a {column} placeholder to the selected text, QR code or barcode"))
        self.insert_menu = QMenu(self.insert)
        self.insert.setMenu(self.insert_menu)
        self.file = QLabel()
        set_tone(self.file, "info")
        self.file.setWordWrap(True)

        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(24)
        self.table.setToolTip(tr("Click a row to see it in the preview"))
        self.only_selected = QCheckBox(tr("Print only the selected rows"))
        self.summary = QLabel()
        self.warning = QLabel()
        set_tone(self.warning, "warn")
        self.warning.setWordWrap(True)

        top = QHBoxLayout()
        top.addWidget(load)
        top.addWidget(self.insert)
        top.addStretch(1)
        top.addWidget(self.unlink)
        bottom = QHBoxLayout()
        bottom.addWidget(self.only_selected)
        bottom.addStretch(1)
        bottom.addWidget(self.summary)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 8)
        layout.addLayout(top)
        layout.addWidget(self.file)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.warning)
        layout.addLayout(bottom)

        self.table.currentCellChanged.connect(lambda row, *_: document.show_record(row))
        self.table.itemSelectionChanged.connect(self._update_summary)
        self.only_selected.toggled.connect(self._update_summary)
        document.data_changed.connect(self.rebuild)
        document.changed.connect(self._update_warning)
        document.changed.connect(self._update_summary)
        self.rebuild()

    # ------------------------------------------------------------------ content

    def rebuild(self) -> None:
        document, table = self.document, self.document.table
        with QSignalBlocker(self.table):
            if table is None or self.table.property("source") != id(table):
                self.table.clear()
                self.table.setProperty("source", id(table) if table else 0)
                if table is not None:
                    self.table.setColumnCount(len(table.columns))
                    self.table.setHorizontalHeaderLabels(table.columns)
                    self.table.setRowCount(len(table))
                    for r, row in enumerate(table.rows):
                        for c, name in enumerate(table.columns):
                            self.table.setItem(r, c, QTableWidgetItem(row[name]))
                    self.table.resizeColumnsToContents()
                else:
                    self.table.setRowCount(0)
                    self.table.setColumnCount(0)
            if table is not None and self.table.currentRow() != document.record:
                self.table.setCurrentCell(document.record, 0)
        self.insert_menu.clear()
        for name in table.columns if table else []:
            self.insert_menu.addAction(f"{{{name}}}", lambda n=name: self.document.insert_field(n))
        self.insert.setEnabled(table is not None)
        self.unlink.setEnabled(bool(document.doc.data_file))
        if document.data_error:
            self.file.setText(tr("The data file cannot be read:\n{error}").format(error=document.data_error))
            set_tone(self.file, "error")
        else:
            path = document.doc.data_file
            self.file.setText(Path(path).name if path else tr("No data file. Load a CSV file with a header row; "
                                                              "every row becomes one label."))
            self.file.setToolTip(path)
            set_tone(self.file, "info")
        self._update_warning()
        self._update_summary()

    def _update_warning(self) -> None:
        table = self.document.table
        missing = merge.missing_columns(self.document.doc, table) if table else []
        self.warning.setText(tr("No column for: {fields}").format(fields=", ".join(f"{{{m}}}" for m in missing))
                             if missing else "")
        self.warning.setVisible(bool(missing))

    def _update_summary(self) -> None:
        records = self.selected_records()
        if records is None:
            self.summary.setText("")
            return
        labels = len(records) * max(1, self.document.doc.copies)
        self.summary.setText(ntr("{count} label", "{count} labels", labels).format(count=labels))

    # ------------------------------------------------------------------ printing

    def selected_records(self) -> list[dict[str, str]] | None:
        """Records to print, None without data table."""
        table = self.document.table
        if table is None:
            return None
        if self.only_selected.isChecked():
            rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
            return table.select(rows)
        return table.select(None)
