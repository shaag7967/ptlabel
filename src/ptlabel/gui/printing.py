"""Printer connection for the GUI: status polling, discovery and print jobs in the background."""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal

from .. import config
from ..i18n import tr
from ..model import LabelDocument
from ..printer import (NetworkPrinter, PrinterError, PrinterInfo, PrinterStatus, discover_printers, open_printer,
                       wait_for_completion)
from ..raster import build_job
from ..render import print_pages
from .qtutil import STATUS_INTERVAL_MS, BackgroundRunner


class PrinterController(QObject):
    status_changed = Signal()                  # ``status``, ``text`` and ``tone`` were updated
    discovery_finished = Signal(list, object, bool)  # printers, error, silent
    print_started = Signal(int)                # number of labels
    print_finished = Signal(int, object, object)  # number of labels, final status or None, error or None

    def __init__(self, cfg: dict, parent: QObject | None = None):
        super().__init__(parent)
        self.cfg = cfg
        self.target: str = cfg.get("printer", "")
        self.status: PrinterStatus | None = None
        self.text = tr("No printer set")
        self.tone = "warn"
        self.busy = False
        self._pending = False
        self._bg = BackgroundRunner(self)
        self._timer = QTimer(self, interval=STATUS_INTERVAL_MS)
        self._timer.timeout.connect(self.refresh)

    # ------------------------------------------------------------------ setup

    def start(self) -> None:
        """Query the configured printer, or search for one first, then poll regularly."""
        if self.target:
            self._start_polling()
        else:
            self.discover(silent=True, then=self._start_polling)

    def _start_polling(self) -> None:
        self.refresh()
        self._timer.start()

    def set_target(self, target: str) -> None:
        target = target.strip()
        if target == self.target:
            return
        self.target = target
        self.cfg["printer"] = target
        config.save(self.cfg)
        self.status = None
        self.refresh(manual=True)

    # ------------------------------------------------------------------ status

    def _set_state(self, text: str, tone: str) -> None:
        self.text, self.tone = text, tone
        self.status_changed.emit()

    def refresh(self, manual: bool = False) -> None:
        target = self.target
        if not target:
            self.status = None
            self._set_state(tr("No printer set – switch the printer on and click “Search…” "
                               "or enter its host name/IP"), "warn")
            return
        if self._pending or self.busy:
            return
        self._pending = True
        if manual:
            self._set_state(tr("Querying {printer} …").format(printer=target), "info")
        self._bg.run(lambda: open_printer(target).status(), self._on_status)

    def _on_status(self, status: PrinterStatus | None, error) -> None:
        self._pending = False
        if error is not None:
            self.status = None
            self._set_state(str(error), "error")
        else:
            self.apply_status(status)

    def apply_status(self, status: PrinterStatus) -> None:
        self.status = status
        self._set_state(f"{status.model}: {status.summary()}", "error" if status.errors else "ok")

    @property
    def tape(self):
        return self.status.tape if self.status else None

    # ------------------------------------------------------------------ discovery

    def discover(self, silent: bool = False, then=None) -> None:
        def done(found: list[PrinterInfo] | None, error) -> None:
            found = found or []
            label_printers = [p for p in found if p.model.upper().startswith(("PT", "QL"))]
            if error is None and len(label_printers) == 1:
                self.set_target(label_printers[0].address)
            else:
                self.discovery_finished.emit(found, error, silent)
            if then:
                then()

        self._bg.run(lambda: discover_printers(2.0), done)

    # ------------------------------------------------------------------ printing

    def print_document(self, doc: LabelDocument) -> None:
        """Render and send ``doc``; raises on rendering errors, reports the rest via signals."""
        pages = print_pages(doc)
        job = build_job(pages, doc.tape, doc.print_options())
        target = self.target
        self.busy = True
        self.print_started.emit(len(pages))

        def work():
            printer = open_printer(target)
            printer.send(job)
            if not isinstance(printer, NetworkPrinter):
                return None
            try:
                return wait_for_completion(printer)
            except PrinterError:  # the job was sent, only the follow-up status failed
                return None

        def done(status, error):
            self.busy = False
            if status is not None:
                self.apply_status(status)
            self.print_finished.emit(len(pages), status, error)

        self._bg.run(work, done)
