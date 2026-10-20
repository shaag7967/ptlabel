"""Printer access: status via SNMP, print jobs via raw TCP (port 9100) or a device/file."""

from __future__ import annotations

import socket
import time
from dataclasses import dataclass
from pathlib import Path

from . import snmp
from .tapes import MEDIA_TYPES, TAPE_COLORS, TEXT_COLORS, Tape, tape_for_code

RAW_PORT = 9100

MODELS = {0x68: "PT-P750W"}

ERRORS_1 = {
    0x01: "Kein Band eingelegt",
    0x04: "Schneidemesser blockiert",
    0x08: "Akku schwach",
    0x40: "Falsches Netzteil",
}
ERRORS_2 = {
    0x01: "Falsches Band – bitte Band wechseln",
    0x02: "Erweiterungspuffer voll",
    0x04: "Übertragungsfehler",
    0x08: "Übertragungspuffer voll",
    0x10: "Abdeckung offen",
    0x20: "Überhitzung",
    0x80: "Systemfehler",
}


class PrinterError(Exception):
    pass


@dataclass
class PrinterStatus:
    raw: bytes
    model_code: int
    error1: int
    error2: int
    media_width: int
    media_type: int
    status_type: int
    phase: int
    tape_color: int
    text_color: int

    @classmethod
    def parse(cls, data: bytes) -> PrinterStatus:
        if len(data) < 32 or data[0] != 0x80 or data[2] != 0x42:
            raise PrinterError("Ungültige Statusantwort")
        return cls(bytes(data[:32]), data[4], data[8], data[9], data[10], data[11],
                   data[18], data[19], data[24], data[25])

    @property
    def model(self) -> str:
        return MODELS.get(self.model_code, f"Modell 0x{self.model_code:02X}")

    @property
    def errors(self) -> list[str]:
        out = [text for bit, text in ERRORS_1.items() if self.error1 & bit]
        out += [text for bit, text in ERRORS_2.items() if self.error2 & bit]
        return out

    @property
    def printing(self) -> bool:
        return self.phase == 0x01

    @property
    def tape(self) -> Tape | None:
        return tape_for_code(self.media_width) if self.media_width else None

    @property
    def tape_color_rgb(self) -> str | None:
        entry = TAPE_COLORS.get(self.tape_color)
        return entry[1] if entry else None

    @property
    def text_color_rgb(self) -> str | None:
        entry = TEXT_COLORS.get(self.text_color)
        return entry[1] if entry else None

    def describe_media(self) -> str:
        if not self.media_width:
            return "kein Band"
        tape = self.tape
        width = tape.label if tape else f"{self.media_width} mm"
        kind = MEDIA_TYPES.get(self.media_type, f"Typ 0x{self.media_type:02X}")
        colors = ""
        if self.tape_color in TAPE_COLORS:
            colors = TAPE_COLORS[self.tape_color][0]
            if self.text_color in TEXT_COLORS:
                colors += " / " + TEXT_COLORS[self.text_color][0]
            colors = ", " + colors
        return f"{width} {kind}{colors}"

    def summary(self) -> str:
        text = f"{self.describe_media()}"
        if self.errors:
            text += " – " + ", ".join(self.errors)
        elif self.printing:
            text += " – druckt"
        else:
            text += " – bereit"
        return text


@dataclass
class PrinterInfo:
    address: str  # host name if it resolves, otherwise the IP
    ip: str
    model: str
    name: str


class NetworkPrinter:
    def __init__(self, host: str, port: int = RAW_PORT, community: str = "public"):
        self.host = host
        self.port = port
        self.community = community

    def status(self, confirm_errors: bool = True) -> PrinterStatus:
        status = self._read_status()
        # The PT-P750W network module flags a "communication error" for a fraction of a second
        # every ~2.8 s, even when idle. Only errors that are still present on re-reading count.
        for _ in range(2):
            if not (confirm_errors and status.errors):
                break
            time.sleep(0.4)
            status = self._read_status()
        return status

    def _read_status(self) -> PrinterStatus:
        try:
            raw = snmp.get(self.host, snmp.OID_BROTHER_STATUS, self.community)
        except (snmp.SnmpError, OSError) as exc:
            raise PrinterError(f"{exc} – Drucker eingeschaltet und im WLAN?") from exc
        if not isinstance(raw, bytes):
            raise PrinterError("Drucker liefert keinen Brother-Status")
        return PrinterStatus.parse(raw)

    def send(self, job: bytes) -> None:
        try:
            with socket.create_connection((self.host, self.port), timeout=10) as sock:
                sock.sendall(job)
                sock.shutdown(socket.SHUT_WR)
                sock.settimeout(2)
                try:
                    while sock.recv(1024):
                        pass
                except (socket.timeout, ConnectionResetError):
                    pass
        except OSError as exc:
            raise PrinterError(f"Senden an {self.host}:{self.port} fehlgeschlagen ({exc})") from exc


class FilePrinter:
    """Writes the job to a file or device node (e.g. /dev/usb/lp0 for USB on Linux)."""

    def __init__(self, path: str):
        self.path = path

    def status(self) -> PrinterStatus:
        raise PrinterError("Status ist nur über das Netzwerk verfügbar")

    def send(self, job: bytes) -> None:
        try:
            with open(self.path, "wb") as fh:
                fh.write(job)
        except OSError as exc:
            raise PrinterError(f"Schreiben nach {self.path} fehlgeschlagen ({exc})") from exc


def open_printer(target: str) -> NetworkPrinter | FilePrinter:
    """``target`` is a host name/IP (optionally ``host:port``), ``file:<path>`` or a /dev path."""
    target = target.strip()
    if not target:
        raise PrinterError("Kein Drucker eingestellt")
    if target.startswith("file:"):
        return FilePrinter(target[5:])
    if target.startswith("/dev/") or Path(target).suffix.lower() in (".bin", ".prn"):
        return FilePrinter(target)
    host, _, port = target.partition(":")
    return NetworkPrinter(host, int(port) if port.isdigit() else RAW_PORT)


def wait_for_completion(printer: NetworkPrinter, timeout: float = 30.0) -> PrinterStatus:
    """Poll the status until the printer is idle again or reports an error."""
    start = time.monotonic()
    seen_printing = False
    time.sleep(1.0)
    while True:
        status = printer.status()
        if status.errors:
            return status
        if status.printing:
            seen_printing = True
        elif seen_printing or time.monotonic() - start > 4:
            return status
        if time.monotonic() - start > timeout:
            return status
        time.sleep(0.7)


def discover_printers(timeout: float = 2.0) -> list[PrinterInfo]:
    found = []
    for ip, value in snmp.discover(snmp.OID_DEVICE_DESCR, timeout=timeout).items():
        model = value.decode("latin-1", "replace") if isinstance(value, bytes) else ""
        if "brother" not in model.lower():
            continue
        name = ""
        try:
            raw = snmp.get(ip, snmp.OID_SYS_NAME, timeout=1.0, retries=1)
            name = raw.decode("latin-1", "replace") if isinstance(raw, bytes) else ""
        except snmp.SnmpError:
            pass
        address = ip
        if name:
            try:
                if socket.gethostbyname(name) == ip:
                    address = name
            except OSError:
                pass
        found.append(PrinterInfo(address, ip, model.replace("Brother ", ""), name))
    return sorted(found, key=lambda p: p.ip)
