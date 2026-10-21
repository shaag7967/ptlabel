"""Printer connection for the GUI: status polling, discovery and print jobs in the background."""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal

from .. import config
from ..i18n import ntr, tr
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
    _progress = Signal(object)                 # status read while a job runs (from the worker thread)

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
        self._progress.connect(self.apply_status)  # queued into the GUI thread

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
        tone = "error" if status.errors else "busy" if status.printing or self.busy else "ok"
        self._set_state(f"{status.model}: {status.summary()}", tone)

    @property
    def activity(self) -> str | None:
        """What the printer is doing right now, or None if it can take a job."""
        printing = self.status is not None and self.status.printing
        if self.busy:
            return tr("Printing …") if printing else tr("Sending …")
        return tr("Printing …") if printing else None

    @property
    def web_url(self) -> str | None:
        """Address of the printer's web page (Web Based Management), None for file/USB targets."""
        target = self.target.strip()
        if not target or target.startswith(("file:", "/")) or target.lower().endswith((".bin", ".prn")):
            return None
        host = target.rsplit(":", 1)[0] if target.count(":") == 1 else target  # drop a raw port like :9100
        return f"http://{host}/"

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

    def print_document(self, doc: LabelDocument, records: list[dict[str, str]] | None = None) -> None:
        """Render and send ``doc`` (once per data record); raises on rendering errors, reports
        the rest via signals."""
        pages = print_pages(doc, records=records)
        job = build_job(pages, doc.tape, doc.print_options())
        target = self.target
        self.busy = True
        self.print_started.emit(len(pages))
        self._set_state(ntr("Sending {count} label …", "Sending {count} labels …", len(pages)).format(
            count=len(pages)), "busy")

        def work():
            printer = open_printer(target)
            printer.send(job)
            if not isinstance(printer, NetworkPrinter):
                return None
            try:
                return wait_for_completion(printer, on_status=self._progress.emit)
            except PrinterError:  # the job was sent, only the follow-up status failed
                return None

        def done(status, error):
            self.busy = False
            if status is not None:
                self.apply_status(status)
            elif error is not None:
                self._set_state(str(error), "error")
            else:
                self.status_changed.emit()
            self.print_finished.emit(len(pages), status, error)

        self._bg.run(work, done)
