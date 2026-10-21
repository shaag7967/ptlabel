"""Menu bar, context menu and main toolbar of the main window."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import QMenu, QSizePolicy, QToolBar, QWidget

from ..i18n import tr
from .actions import INSERT_KINDS
from .icons import icon
from .widgets import PrintButton

if TYPE_CHECKING:
    from .window import MainWindow

THEMES = [("system", tr("System"), "sun-moon"), ("light", tr("Light"), "sun"), ("dark", tr("Dark"), "moon")]


def build_main_toolbar(window: MainWindow) -> QToolBar:
    bar = QToolBar(tr("Main toolbar"))
    bar.setObjectName("main_toolbar")
    bar.setMovable(False)
    a = window.actions
    for key in ("new", "open", "save", None, "undo", "redo", None):
        bar.addSeparator() if key is None else bar.addAction(a[key])
    for kind, _, _ in INSERT_KINDS:
        bar.addAction(a[f"insert_{kind}"])
        bar.widgetForAction(a[f"insert_{kind}"]).setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    bar.addSeparator()
    for key in ("duplicate", "delete", "front", "back", None, "snap"):
        bar.addSeparator() if key is None else bar.addAction(a[key])
    spacer = QWidget()
    spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    bar.addWidget(spacer)
    print_button = PrintButton(window.printer, tr("Print"), icon("printer", "white"))
    print_button.setToolTip(a["print"].toolTip())
    print_button.clicked.connect(a["print"].trigger)
    bar.addWidget(print_button)
    return bar


def fill_object_menu(menu: QMenu, window: MainWindow) -> None:
    a = window.actions
    menu.addActions([a["duplicate"], a["delete"]])
    menu.addSeparator()
    menu.addActions([a["front"], a["back"]])
    menu.addSeparator()
    menu.addActions([a["center_h"], a["center"]])


def build_menu_bar(window: MainWindow) -> None:
    a, bar = window.actions, window.menuBar()
    file = bar.addMenu(tr("&File"))
    file.addActions([a["new"], a["new_cable"], a["new_wrap"], a["open"]])
    file.addMenu(window.recent.menu)
    file.addActions([a["save"], a["save_as"]])
    file.addSeparator()
    file.addAction(a["load_data"])
    file.addAction(a["export"])
    file.addSeparator()
    file.addAction(a["quit"])

    edit = bar.addMenu(tr("&Edit"))
    edit.addActions([a["undo"], a["redo"]])
    edit.addSeparator()
    fill_object_menu(edit, window)

    insert = bar.addMenu(tr("&Insert"))
    insert.addActions([a[f"insert_{kind}"] for kind, _, _ in INSERT_KINDS])

    view = bar.addMenu(tr("&View"))
    view.addActions([a["zoom_in"], a["zoom_out"], a["zoom_auto"]])
    view.addSeparator()
    view.addAction(a["snap"])
    view.addSeparator()
    _build_theme_menu(view.addMenu(icon("sun-moon"), tr("Theme")), window)
    panels = view.addMenu(icon("layers"), tr("Panels and toolbars"))
    panels.addActions([dock.toggleViewAction() for dock in window.docks])
    panels.addSeparator()
    panels.addActions([window.main_toolbar.toggleViewAction(), window.format_bar.toggleViewAction()])
    panels.addSeparator()
    panels.addAction(a["reset_layout"])

    fonts = bar.addMenu(tr("F&onts"))
    fonts.addActions([a["add_fonts"], a["web_fonts"]])
    fonts.addSeparator()
    fonts.addAction(a["all_fonts"])
    fonts.addAction(a["font_folder"])

    printer = bar.addMenu(tr("&Printer"))
    printer.addActions([a["print"], a["status"], a["discover"]])

    help_menu = bar.addMenu(tr("&Help"))
    help_menu.addActions([a["placeholders"], a["usage"], a["about"]])


def _build_theme_menu(menu: QMenu, window: MainWindow) -> None:
    group = QActionGroup(menu)
    for mode, text, name in THEMES:
        action = menu.addAction(icon(name), text)
        action.setCheckable(True)
        action.setChecked(window.theme.mode == mode)
        action.triggered.connect(lambda _=False, m=mode: window.set_theme(m))
        group.addAction(action)
