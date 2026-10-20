"""Command line interface. Without arguments the GUI is started."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, config
from .model import LabelDocument, QRCodeObject, TextObject
from .printer import PrinterError, discover_printers, open_printer, wait_for_completion
from .raster import build_job
from .render import print_pages, render


def _printer_target(args) -> str:
    target = args.printer or config.load().get("printer", "")
    if not target:
        raise PrinterError("Kein Drucker angegeben (--printer HOST) und keiner in der GUI eingestellt")
    return target


def _output(doc: LabelDocument, args) -> int:
    if args.preview:
        render(doc).image.point(lambda v: 0 if v else 255).save(args.preview)
        print(f"Vorschau gespeichert: {args.preview}")
    job = build_job(print_pages(doc), doc.tape, doc.print_options())
    if args.output:
        Path(args.output).write_bytes(job)
        print(f"Druckdaten gespeichert: {args.output} ({len(job)} Bytes)")
    if args.preview or args.output:
        if not args.printer:
            return 0
    printer = open_printer(_printer_target(args))
    if hasattr(printer, "host"):
        status = printer.status()
        if status.errors:
            raise PrinterError(", ".join(status.errors))
        if status.tape and status.tape.code != doc.tape.code:
            raise PrinterError(f"Eingelegtes Band ({status.tape.label}) passt nicht zum Etikett ({doc.tape.label})")
    printer.send(job)
    if hasattr(printer, "host"):
        status = wait_for_completion(printer)
        if status.errors:
            raise PrinterError(", ".join(status.errors))
    print(f"{doc.copies} Etikett(en) gedruckt.")
    return 0


def cmd_status(args) -> int:
    printer = open_printer(_printer_target(args))
    status = printer.status()
    print(f"Drucker: {status.model}")
    print(f"Band:    {status.describe_media()}")
    print(f"Zustand: {', '.join(status.errors) if status.errors else ('druckt' if status.printing else 'bereit')}")
    return 1 if status.errors else 0


def cmd_discover(args) -> int:
    printers = discover_printers()
    if not printers:
        print("Kein Brother-Drucker gefunden.")
        return 1
    for p in printers:
        print(f"{p.address:24} {p.ip:16} {p.model}")
    return 0


def cmd_print(args) -> int:
    doc = LabelDocument.load(args.file)
    if args.copies:
        doc.copies = args.copies
    if args.start is not None:
        doc.counter_start = args.start
    return _output(doc, args)


def cmd_text(args) -> int:
    lines = "\n".join(args.text).replace("\\n", "\n")
    tape_mm = args.tape
    if tape_mm is None:
        tape_mm = 12.0
        try:
            status = open_printer(_printer_target(args)).status()
            if status.tape:
                tape_mm = status.tape.width_mm
        except PrinterError:
            pass
    doc = LabelDocument(tape_mm=tape_mm, margin_mm=args.margin, copies=args.copies)
    if args.length:
        doc.auto_length = False
        doc.length_mm = args.length
    x = doc.margin_mm
    if args.qr:
        qr = QRCodeObject(x=x, data=args.qr, size=round(doc.tape.print_mm, 1))
        qr.y = doc.tape.band_top_mm
        doc.objects.append(qr)
        x += qr.size + 1.5
    text = TextObject(x=x, text=lines, font=args.font or "", bold=args.bold, italic=args.italic,
                      align=args.align)
    if args.size:
        text.auto_size = False
        text.size = args.size
        text.y = doc.tape.band_top_mm
    doc.objects.append(text)
    return _output(doc, args)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ptlabel", description="Etiketten für den Brother PT-P750W erstellen und drucken. "
                                     "Ohne Befehl startet die grafische Oberfläche.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="cmd", metavar="BEFEHL")

    sub.add_parser("gui", help="grafische Oberfläche starten (Standard)")

    p = sub.add_parser("status", help="Druckerstatus anzeigen")
    p.add_argument("--printer", help="Hostname/IP des Druckers")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("discover", help="Brother-Drucker im Netzwerk suchen")
    p.set_defaults(func=cmd_discover)

    def output_args(p):
        p.add_argument("--printer", help="Hostname/IP, file:PFAD oder /dev/usb/lp0")
        p.add_argument("--preview", metavar="PNG", help="Vorschau als PNG speichern (druckt nur zusätzlich mit --printer)")
        p.add_argument("--output", metavar="DATEI", help="Druckdaten in Datei schreiben (druckt nur zusätzlich mit --printer)")

    p = sub.add_parser("print", help="Etikettendatei (.ptlabel) drucken")
    p.add_argument("file")
    p.add_argument("--copies", type=int)
    p.add_argument("--start", type=int, help="Startwert für {nr}")
    output_args(p)
    p.set_defaults(func=cmd_print)

    p = sub.add_parser("text", help="schnell ein Text-Etikett drucken (jedes Argument = eine Zeile)")
    p.add_argument("text", nargs="+")
    p.add_argument("--tape", type=float, help="Bandbreite in mm (Standard: eingelegtes Band)")
    p.add_argument("--font", help="Schriftart, z. B. Arial")
    p.add_argument("--size", type=float, help="Schriftgröße in pt (Standard: automatisch)")
    p.add_argument("--bold", action="store_true")
    p.add_argument("--italic", action="store_true")
    p.add_argument("--align", choices=("left", "center", "right"), default="left")
    p.add_argument("--qr", metavar="INHALT", help="QR-Code vor den Text setzen")
    p.add_argument("--length", type=float, help="feste Etikettlänge in mm")
    p.add_argument("--margin", type=float, default=2.0, help="Rand in mm (Standard 2)")
    p.add_argument("--copies", type=int, default=1)
    output_args(p)
    p.set_defaults(func=cmd_text)

    args = parser.parse_args(argv)
    if args.cmd in (None, "gui"):
        from .gui import run
        return run()
    try:
        return args.func(args)
    except (PrinterError, OSError, ValueError) as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1
