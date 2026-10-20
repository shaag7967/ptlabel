"""PySide6 user interface (Windows and Linux)."""

from __future__ import annotations

import sys

from PySide6.QtCore import QLibraryInfo, QLocale, QLoggingCategory, QTranslator
from PySide6.QtWidgets import QApplication

from .. import i18n
from .qtutil import APP_NAME, app_icon

# Qt's Wayland text input reports harmless focus mismatches on every focus change (Qt bug).
QUIET_LOGGING = "qt.qpa.wayland.textinput=false"


def run() -> int:
    from .window import MainWindow

    QLoggingCategory.setFilterRules(QUIET_LOGGING)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(app_icon())
    translator = QTranslator(app)  # standard dialogs and buttons in the same language as PT-Label
    translations = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if translator.load(QLocale(i18n.language()), "qtbase", "_", translations):
        app.installTranslator(translator)
    window = MainWindow()
    window.show()
    return app.exec()
