"""User-facing steps around printing: confirmations, printer search and result messages."""

from __future__ import annotations

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QWidget

from .. import merge
from ..i18n import ntr, tr
from . import dialogs
from .document import DocumentController
from .printing import PrinterController
from .statusbar import StatusBar


class PrintWorkflow(QObject):
    def __init__(self, parent: QWidget, document: DocumentController, printer: PrinterController,
                 status: StatusBar, records=None):
        """``records()`` returns the data records to print (None without series printing)."""
        super().__init__(parent)
        self.records = records or (lambda: None)
        self.parent_widget = parent
        self.document, self.printer, self.status = document, printer, status
        self._tape_checked = False
        printer.status_changed.connect(self._status_changed)
        printer.discovery_finished.connect(self._discovery_finished)
        printer.print_started.connect(self._print_started)
        printer.print_finished.connect(self._print_finished)

    # ------------------------------------------------------------------ tape

    def _status_changed(self) -> None:
        tape = self.printer.tape
        if tape and not self._tape_checked:
            self._tape_checked = True  # an untouched new label follows the loaded tape once
            if self.document.is_pristine() and tape.width_mm != self.document.doc.tape_mm:
                self.document.new(tape.width_mm)

    def adopt_tape(self) -> None:
        tape = self.printer.tape
        if tape:
            self.document.set_label(tape_mm=tape.width_mm)

    # ------------------------------------------------------------------ discovery

    def discover(self) -> None:
        self.status.show_message(tr("Searching the network for Brother printers …"), sticky=True)
        self.printer.discover(then=lambda: self.status.show_message(""))

    def _discovery_finished(self, found: list, error, silent: bool) -> None:
        if silent:
            return
        parent = self.parent_widget
        if error is not None:
            dialogs.error(parent, tr("Search failed:\n{error}").format(error=error))
        elif found:
            address = dialogs.choose_printer(parent, found)
            if address:
                self.printer.set_target(address)
        else:
            dialogs.info(parent, tr("No Brother printer found.\nPlease enter the host name or IP address by hand."))

    # ------------------------------------------------------------------ printing

    def print_label(self) -> None:
        printer, document, parent = self.printer, self.document, self.parent_widget
        if printer.busy:
            return
        document.flush()
        if not printer.target:
            if dialogs.confirm(parent, tr("No printer is set. Search the network now?")):
                self.discover()
            return
        tape, label_tape = printer.tape, document.doc.tape
        if tape and tape.code != label_tape.code and not dialogs.confirm(parent, tr(
                "The printer has {loaded} tape loaded, the label is designed for {label}.\n\nPrint anyway?").format(
                    loaded=tape.label, label=label_tape.label)):
            return
        records = self.records()
        if records is not None:
            missing = merge.missing_columns(document.doc, document.table)
            if missing and not dialogs.confirm(parent, tr(
                    "The data file has no column for {fields}. These placeholders stay as they are.\n\n"
                    "Print anyway?").format(fields=", ".join(f"{{{m}}}" for m in missing))):
                return
            if not records:
                dialogs.info(parent, tr("No rows selected in the data table."))
                return
        try:
            printer.print_document(document.doc, records)
        except Exception as exc:
            dialogs.error(parent, tr("The label cannot be created:\n{error}").format(error=exc))

    def _print_started(self, count: int) -> None:
        self.status.show_message(ntr("Sending {count} label to {printer} …", "Sending {count} labels to {printer} …",
                                     count).format(count=count, printer=self.printer.target), sticky=True)

    def _print_finished(self, count: int, status, error) -> None:
        if error is not None:
            self.status.show_message(tr("Printing failed"), "error")
            dialogs.error(self.parent_widget, tr("Printing failed:\n{error}").format(error=error))
        elif status is not None and status.errors:
            self.status.show_message(tr("The printer reports an error"), "error")
            dialogs.error(self.parent_widget, tr("The printer reports:") + "\n" + "\n".join(status.errors))
        else:
            self.status.show_message(ntr("{count} label printed", "{count} labels printed", count).format(
                count=count), "ok")
