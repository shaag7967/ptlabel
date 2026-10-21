"""Create the screenshots for the README in docs/screenshots (offscreen, with example data).

Run from the project folder:  .venv/bin/python tools/make_screenshots.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
SIZE = (1600, 980)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("LANGUAGE", "en")
_home = tempfile.TemporaryDirectory()  # clean settings, the user's configuration stays untouched
for var in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
    os.environ[var] = os.path.join(_home.name, var)

from PySide6.QtWidgets import QApplication  # noqa: E402

from ptlabel import fonts, webfonts  # noqa: E402
from ptlabel.gui import create_app, fontui, printing  # noqa: E402
from ptlabel.gui.theme import ThemeManager  # noqa: E402
from ptlabel.gui.window import MainWindow  # noqa: E402
from ptlabel.model import QRCodeObject  # noqa: E402
from ptlabel.printer import PrinterStatus  # noqa: E402

# PT-P750W, 12 mm laminated tape yellow/black (a status block read from the real printer)
STATUS = bytes.fromhex("80 20 42 30 68 30 04 00 00 00 0c 01 00 00 00 00"
                       "00 00 00 00 00 00 00 00 06 08 00 00 00 00 00 00")
FONT = "Atkinson Hyperlegible"
CSV = "Cable;From;To\nK-001;SW01-P12;PP03-24\nK-002;SW01-P13;PP03-25\nK-003;SW01-P14;PP03-26\n" \
      "K-004;Server 1 eth0;SW02-P01\nK-005;Server 2 eth0;SW02-P02\n"


def settle(app: QApplication, window: MainWindow) -> None:
    for _ in range(3):
        app.processEvents()
        window.document.render_now()
    for _ in range(10):
        app.processEvents()


def make_window(app: QApplication, theme: str) -> MainWindow:
    window = MainWindow(ThemeManager(app, theme), {"printer": "192.0.2.10", "snapping": True})
    window.resize(*SIZE)
    window.show()
    window.printer.apply_status(PrinterStatus.parse(STATUS))
    return window


def start(window: MainWindow, layout: str = "normal") -> None:
    document = window.document
    document._saved = document.doc.to_json()  # no "save changes?" question
    document.new(12, layout)


def server_label(window: MainWindow) -> None:
    start(window)
    document = window.document
    text = document.doc.objects[0]
    document.set_property(text, "text", "Server 1\nRack B · HE 12")
    document.set_property(text, "font", FONT)
    document.render_now()
    document.add_object(document.create_object("qrcode"))
    document.set_property(document.selected, "data", "https://intranet.example.org/server1")
    document.select(text)


def shoot(app: QApplication, window: MainWindow, name: str) -> None:
    settle(app, window)
    window.grab().save(str(OUT / name))
    print("saved", OUT / name)


def font_dialog(app: QApplication, window: MainWindow) -> None:
    """Google Fonts dialog with a few entries; the preview uses a bundled font (no network)."""
    families = [("atkinson-hyperlegible", "Atkinson Hyperlegible", "sans-serif"),
                ("barlow-condensed", "Barlow Condensed", "sans-serif"), ("bitter", "Bitter", "serif"),
                ("jetbrains-mono", "JetBrains Mono", "monospace"), ("lobster", "Lobster", "display"),
                ("roboto-condensed", "Roboto Condensed", "sans-serif")]
    entries = [webfonts.WebFont(i, f, c, (400, 700), ("normal", "italic"), "OFL-1.1") for i, f, c in families]
    sample = next((fonts.BUNDLED_FONT_DIR / "barlow-condensed").glob("*400-normal.ttf"))
    with mock.patch.object(webfonts, "list_fonts", return_value=entries), \
            mock.patch.object(webfonts, "download_regular", return_value=sample):
        dialog = fontui.WebFontDialog(window)
        dialog.show()
        for _ in range(30):
            app.processEvents()
            time.sleep(0.02)
        dialog.list.setCurrentRow(1)
        for _ in range(30):
            app.processEvents()
            time.sleep(0.02)
        dialog.grab().save(str(OUT / "fonts.png"))
        print("saved", OUT / "fonts.png")
        dialog.close()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    app = create_app()
    with mock.patch.object(printing, "discover_printers", return_value=[]):
        window = make_window(app, "light")
        server_label(window)
        shoot(app, window, "main.png")

        start(window, "cable_flag")
        document = window.document
        document.set_property(document.doc.objects[0], "text", "SW01-P12")
        document.set_property(document.doc.objects[0], "font", FONT)
        window.label_dock.raise_()
        shoot(app, window, "cable-flag.png")

        start(window, "cable_wrap")
        document.set_property(document.doc.objects[0], "text", "K-001")
        document.set_label(cable_diameter_mm=8)
        shoot(app, window, "cable-wrap.png")

        start(window, "cable_flag")
        csv_file = Path(_home.name) / "cables.csv"
        csv_file.write_text(CSV, encoding="utf-8")
        document.set_data_file(str(csv_file))
        text = document.doc.objects[0]
        document.select(text)
        document.set_property(text, "text", "{Cable}\n{From} – {To}")
        document.set_property(text, "font", FONT)
        window.data_dock.show()
        window.data_panel.table.setCurrentCell(3, 0)
        shoot(app, window, "series.png")

        dark = make_window(app, "dark")
        server_label(dark)
        shoot(app, dark, "dark.png")

        font_dialog(app, window)
    return 0


if __name__ == "__main__":
    sys.exit(main())
