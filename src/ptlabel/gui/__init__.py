"""PySide6 user interface (Windows and Linux)."""

from __future__ import annotations

import sys

from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
from PySide6.QtWidgets import QApplication

from .. import config, i18n
from . import qtlog
from .qtutil import APP_NAME, app_icon


def create_app() -> QApplication:
    qtlog.install()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(app_icon())
    QLocale.setDefault(QLocale(i18n.language()))  # numbers like 1.5 / 1,5 match the language of the texts
    translator = QTranslator(app)  # standard dialogs and buttons in the same language as PT-Label
    translations = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if translator.load(QLocale(i18n.language()), "qtbase", "_", translations):
        app.installTranslator(translator)
    return app


def run() -> int:
    from .theme import ThemeManager
    from .window import MainWindow

    app = create_app()
    cfg = config.load()
    theme = ThemeManager(app, cfg.get("theme", "system"))
    window = MainWindow(theme, cfg)
    window.show()
    return app.exec()
