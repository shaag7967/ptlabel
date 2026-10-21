"""Command line interface. Without arguments the GUI is started."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, config
from .i18n import ntr, tr
from .model import CABLE_FLAG, LabelDocument, QRCodeObject, TextObject
from .printer import PrinterError, discover_printers, open_printer, wait_for_completion
from .raster import build_job
from .render import print_pages, render


def _printer_target(args) -> str:
    target = args.printer or config.load().get("printer", "")
    if not target:
        raise PrinterError(tr("No printer given (--printer HOST) and none set in the GUI"))
    return target


def _output(doc: LabelDocument, args) -> int:
    if args.preview:
        render(doc).image.point(lambda v: 0 if v else 255).save(args.preview)
        print(tr("Preview saved: {path}").format(path=args.preview))
    job = build_job(print_pages(doc), doc.tape, doc.print_options())
    if args.output:
        Path(args.output).write_bytes(job)
        print(tr("Print data saved: {path} ({size} bytes)").format(path=args.output, size=len(job)))
    if args.preview or args.output:
        if not args.printer:
            return 0
    printer = open_printer(_printer_target(args))
    if hasattr(printer, "host"):
        status = printer.status()
        if status.errors:
            raise PrinterError(", ".join(status.errors))
        if status.tape and status.tape.code != doc.tape.code:
            raise PrinterError(tr("Loaded tape ({loaded}) does not match the label ({label})").format(
                loaded=status.tape.label, label=doc.tape.label))
    printer.send(job)
    if hasattr(printer, "host"):
        status = wait_for_completion(printer)
        if status.errors:
            raise PrinterError(", ".join(status.errors))
    print(ntr("{count} label printed.", "{count} labels printed.", doc.copies).format(count=doc.copies))
    return 0


def cmd_status(args) -> int:
    printer = open_printer(_printer_target(args))
    status = printer.status()
    state = ", ".join(status.errors) if status.errors else (tr("printing") if status.printing else tr("ready"))
    print(tr("Printer: {model}").format(model=status.model))
    print(tr("Tape:    {media}").format(media=status.describe_media()))
    print(tr("State:   {state}").format(state=state))
    return 1 if status.errors else 0


def cmd_discover(args) -> int:
    printers = discover_printers()
    if not printers:
        print(tr("No Brother printer found."))
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


def _text_document(args, layout: str = "normal") -> LabelDocument:
    """Label with the given text lines (and optionally a QR code in front) for the text and cable commands."""
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
    doc = LabelDocument(tape_mm=tape_mm, layout=layout, margin_mm=args.margin, copies=args.copies)
    if getattr(args, "start", None) is not None:
        doc.counter_start = args.start
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
    return doc


def cmd_text(args) -> int:
    return _output(_text_document(args), args)


def cmd_cable(args) -> int:
    doc = _text_document(args, CABLE_FLAG)
    doc.cable_diameter_mm = args.diameter
    doc.fold_marks = not args.no_fold_marks
    if not args.qr:  # a lone text sits in the middle of the flag
        doc.objects[-1].h_align = "center"
    return _output(doc, args)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ptlabel", description=tr(
        "Design and print labels for the Brother PT-P750W. Without a command the graphical user interface starts."))
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="cmd", metavar=tr("COMMAND"))

    sub.add_parser("gui", help=tr("start the graphical user interface (default)"))

    p = sub.add_parser("status", help=tr("show the printer status"))
    p.add_argument("--printer", help=tr("host name/IP of the printer"))
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("discover", help=tr("search the network for Brother printers"))
    p.set_defaults(func=cmd_discover)

    def output_args(p):
        p.add_argument("--printer", help=tr("host name/IP, file:PATH or /dev/usb/lp0"))
        p.add_argument("--preview", metavar="PNG", help=tr("save a preview as PNG (prints only with --printer)"))
        p.add_argument("--output", metavar=tr("FILE"),
                       help=tr("write the print data to a file (prints only with --printer)"))

    p = sub.add_parser("print", help=tr("print a label file (.ptlabel)"))
    p.add_argument("file")
    p.add_argument("--copies", type=int)
    p.add_argument("--start", type=int, help=tr("start value for {nr}"))
    output_args(p)
    p.set_defaults(func=cmd_print)

    def text_args(p, align="left", length_help=tr("fixed label length in mm")):
        p.add_argument("text", nargs="+")
        p.add_argument("--tape", type=float, help=tr("tape width in mm (default: loaded tape)"))
        p.add_argument("--font", help=tr("font, e.g. Arial"))
        p.add_argument("--size", type=float, help=tr("font size in pt (default: automatic)"))
        p.add_argument("--bold", action="store_true")
        p.add_argument("--italic", action="store_true")
        p.add_argument("--align", choices=("left", "center", "right"), default=align)
        p.add_argument("--qr", metavar=tr("CONTENT"), help=tr("put a QR code in front of the text"))
        p.add_argument("--length", type=float, help=length_help)
        p.add_argument("--margin", type=float, default=2.0, help=tr("margin in mm (default 2)"))
        p.add_argument("--copies", type=int, default=1)
        output_args(p)

    p = sub.add_parser("text", help=tr("quickly print a text label (one argument per line)"))
    text_args(p)
    p.set_defaults(func=cmd_text)

    p = sub.add_parser("cable", help=tr("print a cable flag: the same text on both sides of the cable"))
    text_args(p, "center", tr("fixed length of one flag in mm (default: fits the text)"))
    p.add_argument("--diameter", type=float, default=6.0, help=tr("cable diameter in mm (default 6)"))
    p.add_argument("--start", type=int, help=tr("start value for {nr}"))
    p.add_argument("--no-fold-marks", action="store_true", help=tr("do not print fold marks"))
    p.set_defaults(func=cmd_cable)

    args = parser.parse_args(argv)
    if args.cmd in (None, "gui"):
        from .gui import run
        return run()
    try:
        return args.func(args)
    except (PrinterError, OSError, ValueError) as exc:
        print(tr("Error: {error}").format(error=exc), file=sys.stderr)
        return 1
