"""PySide6 user interface (Windows and Linux)."""

from __future__ import annotations

import sys

from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
from PySide6.QtWidgets import QApplication

from .qtutil import APP_NAME, app_icon


def run() -> int:
    from .window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setDesktopFileName("ptlabel")
    app.setWindowIcon(app_icon())
    translator = QTranslator(app)  # German texts for standard dialogs and buttons
    if translator.load(QLocale.system(), "qtbase", "_", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(translator)
    window = MainWindow()
    window.show()
    return app.exec()
