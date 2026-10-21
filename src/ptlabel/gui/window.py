"""Main window: puts canvas, docks, toolbars and menus together and handles files and fonts."""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from PySide6.QtCore import QByteArray, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDockWidget, QFileDialog, QMainWindow, QMenu, QWidget

from .. import config, fonts
from ..i18n import tr
from ..model import CABLE_FLAG, ImageObject
from ..tapes import DPI
from . import dialogs, menus
from .actions import INSERT_KINDS, Actions
from .canvas import LabelCanvas
from .document import DocumentController
from .fontui import FONT_LIST, WebFontDialog
from .format_toolbar import FormatToolBar
from .label_panel import LabelPanel
from .objects_panel import ObjectsPanel
from .preview import colorize
from .print_panel import PrintPanel
from .print_workflow import PrintWorkflow
from .printing import PrinterController
from .properties import PropertyEditor
from .qtutil import APP_NAME
from .recent import RecentFiles
from .statusbar import StatusBar
from .theme import ThemeManager
from .widgets import scrolling

STATE_VERSION = 2
DOCK_WIDTHS = (380, 210)  # right and left dock area on first start


class MainWindow(QMainWindow):
    def __init__(self, theme: ThemeManager, cfg: dict | None = None):
        super().__init__()
        self.cfg = cfg if cfg is not None else config.load()
        self.theme = theme
        self.document = DocumentController(self)
        self.printer = PrinterController(self.cfg, self)
        self.recent = RecentFiles(self.cfg, self)
        FONT_LIST.set_show_all(bool(self.cfg.get("show_all_fonts", False)))
        self.actions = Actions(self)

        self.canvas = LabelCanvas(self.document, theme)
        self.canvas.zoom = int(self.cfg.get("zoom") or 0)
        self.canvas.snapping = bool(self.cfg.get("snapping", True))
        self.setCentralWidget(self.canvas.scroll)
        self.properties = PropertyEditor(self.document)
        self.label_panel = LabelPanel(self.document)
        self.print_panel = PrintPanel(self.document, self.printer, theme)
        self.objects_panel = ObjectsPanel(self.document)
        self.format_bar = FormatToolBar(self.document)
        self.status = StatusBar(self.document, self.printer, self.canvas, theme)
        self.setStatusBar(self.status)
        self.workflow = PrintWorkflow(self, self.document, self.printer, self.status)

        self._build_docks()
        self.main_toolbar = menus.build_main_toolbar(self)
        self.addToolBar(self.main_toolbar)
        self.addToolBarBreak()
        self.addToolBar(self.format_bar)
        menus.build_menu_bar(self)
        self.context_menu = QMenu(self)
        menus.fill_object_menu(self.context_menu, self)
        self._connect()
        self._restore_layout()
        self.document.new()
        QTimer.singleShot(300, self.printer.start)

    # ------------------------------------------------------------------ layout

    def _dock(self, name: str, title: str, widget: QWidget, area: Qt.DockWidgetArea,
              scroll: bool = True) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(name)
        dock.setWidget(scrolling(widget) if scroll else widget)
        self.addDockWidget(area, dock)
        return dock

    def _build_docks(self) -> None:
        right, left = Qt.DockWidgetArea.RightDockWidgetArea, Qt.DockWidgetArea.LeftDockWidgetArea
        self.setDockOptions(QMainWindow.DockOption.AnimatedDocks | QMainWindow.DockOption.AllowTabbedDocks)
        self.properties_dock = self._dock("properties_dock", tr("Properties"), self.properties, right)
        self.label_dock = self._dock("label_dock", tr("Label"), self.label_panel, right)
        self.print_dock = self._dock("print_dock", tr("Print"), self.print_panel, right)
        self.objects_dock = self._dock("objects_dock", tr("Objects"), self.objects_panel, left, scroll=False)
        self.tabifyDockWidget(self.label_dock, self.print_dock)
        self.label_dock.raise_()

    @property
    def docks(self) -> list[QDockWidget]:
        return [self.properties_dock, self.label_dock, self.print_dock, self.objects_dock]

    def _connect(self) -> None:
        a, doc, canvas, workflow = self.actions, self.document, self.canvas, self.workflow
        a.connect({
            "new": self.new_document, "new_cable": lambda: self.new_document(CABLE_FLAG),
            "open": self.open_document, "save": self.save_document,
            "save_as": self.save_document_as, "export": self.export_png, "quit": self.close,
            "undo": doc.undo, "redo": doc.redo, "duplicate": doc.duplicate_selected, "delete": doc.delete_selected,
            "front": lambda: doc.restack(1), "back": lambda: doc.restack(-1), "center": doc.center_vertically,
            "center_h": doc.center_horizontally,
            "zoom_in": lambda: canvas.zoom_by(1), "zoom_out": lambda: canvas.zoom_by(-1),
            "zoom_auto": lambda: canvas.set_zoom(0), "reset_layout": self.reset_layout,
            "print": workflow.print_label, "status": lambda: self.printer.refresh(manual=True),
            "discover": workflow.discover, "add_fonts": self.add_font_files,
            "web_fonts": self.download_fonts, "font_folder": self.open_font_folder,
            "placeholders": lambda: dialogs.show_placeholders(self), "usage": lambda: dialogs.show_usage(self),
            "about": lambda: dialogs.show_about(self),
            **{f"insert_{kind}": (lambda k=kind: self.insert(k)) for kind, _, _ in INSERT_KINDS},
        })
        a["all_fonts"].setChecked(FONT_LIST.show_all)
        a["all_fonts"].toggled.connect(self._show_all_fonts)
        a["snap"].setChecked(canvas.snapping)
        a["snap"].toggled.connect(lambda on: setattr(canvas, "snapping", on))
        # Delete only acts on the canvas; text fields keep their own Delete key
        a["delete"].setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        canvas.addAction(a["delete"])

        canvas.context_menu_requested.connect(self.context_menu.exec)
        canvas.edit_text_requested.connect(self._edit_text)
        self.properties.image_requested.connect(self.load_image_for_selected)
        self.print_panel.print_requested.connect(workflow.print_label)
        self.print_panel.printer_card.search_requested.connect(workflow.discover)
        self.status.adopt_tape_requested.connect(workflow.adopt_tape)
        self.status.printer_clicked.connect(lambda: self.printer.refresh(manual=True))
        self.recent.open_requested.connect(self.open_document)
        self.printer.status_changed.connect(self._show_tape_colors)
        self.printer.status_changed.connect(lambda: a["print"].setEnabled(self.printer.activity is None))
        doc.state_changed.connect(self._update_state)
        doc.selection_changed.connect(self._update_state)

    def _restore_layout(self) -> None:
        self.resize(1360, 820)
        self._default_state = self.saveState(STATE_VERSION)
        self._default_dock_sizes()
        geometry, state = self.cfg.get("window_geometry"), self.cfg.get("window_state")
        if geometry:
            self.restoreGeometry(QByteArray.fromBase64(geometry.encode("ascii")))
        if state:
            self.restoreState(QByteArray.fromBase64(state.encode("ascii")), STATE_VERSION)

    def _default_dock_sizes(self) -> None:
        self.resizeDocks([self.properties_dock, self.objects_dock], list(DOCK_WIDTHS), Qt.Orientation.Horizontal)
        self.resizeDocks([self.properties_dock, self.label_dock], [520, 300], Qt.Orientation.Vertical)

    def reset_layout(self) -> None:
        for dock in self.docks:
            dock.setFloating(False)
            dock.show()
        self.restoreState(self._default_state, STATE_VERSION)
        self._default_dock_sizes()

    def set_theme(self, mode: str) -> None:
        self.theme.set_mode(mode)
        self.cfg["theme"] = mode

    def _update_state(self) -> None:
        doc = self.document
        self.setWindowTitle(f"{'*' if doc.is_modified() else ''}{doc.name} – {APP_NAME}")
        self.actions["undo"].setEnabled(doc.history.can_undo())
        self.actions["redo"].setEnabled(doc.history.can_redo())
        for key in ("duplicate", "delete", "front", "back", "center", "center_h"):
            self.actions[key].setEnabled(doc.selected is not None)

    def _edit_text(self) -> None:
        self.properties_dock.show()
        self.properties_dock.raise_()
        self.properties.focus_text()

    def _show_tape_colors(self) -> None:
        status = self.printer.status
        self.canvas.set_tape_colors(status.tape_color_rgb if status else None,
                                    status.text_color_rgb if status else None)

    # ------------------------------------------------------------------ files

    def _start_dir(self) -> str:
        path = self.document.path
        return str(path.parent) if path else self.cfg.get("last_dir") or str(Path.home())

    def _confirm_discard(self) -> bool:
        self.document.flush()
        if not self.document.is_modified():
            return True
        answer = dialogs.ask_save_changes(self)
        return answer == "discard" or (answer == "save" and self.save_document())

    def new_document(self, layout: str = "normal") -> None:
        if self._confirm_discard():
            tape = self.printer.tape
            self.document.new(tape.width_mm if tape else self.document.doc.tape_mm, layout)

    def open_document(self, name: str | None = None) -> None:
        if not self._confirm_discard():
            return
        name = name or dialogs.open_label_name(self, self._start_dir())
        if not name:
            return
        try:
            self.document.open(name)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            dialogs.error(self, tr("The file cannot be opened:\n{error}").format(error=exc))
            return
        self._remember(Path(name))

    def save_document(self) -> bool:
        if self.document.path is None:
            return self.save_document_as()
        try:
            self.document.save()
        except OSError as exc:
            dialogs.error(self, tr("Saving failed:\n{error}").format(error=exc))
            return False
        self._remember(self.document.path)
        self.status.show_message(tr("Saved: {name}").format(name=self.document.name), "ok")
        return True

    def save_document_as(self) -> bool:
        path = dialogs.save_name(self, tr("Save label"), self._start_dir(), dialogs.LABEL_FILTER, ".ptlabel")
        if path is None:
            return False
        self.document.path = path
        return self.save_document()

    def _remember(self, path: Path) -> None:
        self.cfg["last_dir"] = str(path.parent)
        self.recent.add(path)

    def export_png(self) -> None:
        path = dialogs.save_name(self, tr("Export as PNG"), self._start_dir(), "PNG (*.png)", ".png")
        if path is None:
            return
        self.document.render_now()
        img = colorize(self.document.result, self.canvas.tape_rgb, self.canvas.ink_rgb)
        img = img.resize((img.width * 4, img.height * 4), Image.Resampling.NEAREST)
        try:
            img.save(path, dpi=(DPI * 4, DPI * 4))
        except OSError as exc:
            dialogs.error(self, tr("Export failed:\n{error}").format(error=exc))
            return
        self.status.show_message(tr("Exported: {name}").format(name=path.name), "ok")

    def closeEvent(self, event) -> None:
        if not self._confirm_discard():
            event.ignore()
            return
        self.cfg.pop("geometry", None)  # Tk geometry string of version 1.0
        self.cfg["window_geometry"] = bytes(self.saveGeometry().toBase64()).decode("ascii")
        self.cfg["window_state"] = bytes(self.saveState(STATE_VERSION).toBase64()).decode("ascii")
        self.cfg["zoom"] = self.canvas.zoom
        self.cfg["snapping"] = self.canvas.snapping
        config.save(self.cfg)
        event.accept()

    # ------------------------------------------------------------------ objects

    def insert(self, kind: str) -> None:
        image = None
        if kind == "image":
            image = dialogs.read_image(self, self._start_dir())
            if image is None:
                return
        self.document.add_object(self.document.create_object(kind, image))

    def load_image_for_selected(self) -> None:
        obj = self.document.selected
        if isinstance(obj, ImageObject):
            image = dialogs.read_image(self, self._start_dir())
            if image is not None:
                self.document.set_image(obj, *image)
                self.properties.rebuild()

    # ------------------------------------------------------------------ fonts

    def add_font_files(self) -> None:
        names, _ = QFileDialog.getOpenFileNames(self, tr("Add font files"), self._start_dir(), dialogs.FONT_FILTER)
        if not names:
            return
        try:
            families = fonts.install_font_files(names)
        except OSError as exc:
            dialogs.error(self, tr("The fonts cannot be added:\n{error}").format(error=exc))
            return
        if not families:
            dialogs.info(self, tr("The selected files are not usable fonts."))
            return
        self._fonts_changed(families)

    def download_fonts(self) -> None:
        dialog = WebFontDialog(self)
        dialog.installed.connect(self._fonts_changed)
        dialog.exec()

    def open_font_folder(self) -> None:
        folder = fonts.user_font_dir()
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _show_all_fonts(self, show_all: bool) -> None:
        FONT_LIST.set_show_all(show_all)
        self.cfg["show_all_fonts"] = show_all

    def _fonts_changed(self, families: list[str]) -> None:
        FONT_LIST.refresh()
        self.properties.refresh()
        self.document.schedule_render()
        self.status.show_message(tr("Fonts added: {families}").format(families=", ".join(families)), "ok")
