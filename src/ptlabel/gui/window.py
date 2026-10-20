"""Main window: menus, document state, undo, files and printer handling."""

from __future__ import annotations

import base64
import io
from pathlib import Path

from PIL import Image, ImageDraw
from PySide6.QtCore import QByteArray, QSignalBlocker, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QGridLayout, QGroupBox, QLabel,
                               QListWidget, QMainWindow, QMenu, QMessageBox, QPushButton, QScrollArea,
                               QSizePolicy, QSplitter, QToolBar, QVBoxLayout, QWidget)

from .. import __version__, config, fonts
from ..model import (PLACEHOLDER_HELP, BarcodeObject, FrameObject, ImageObject, LabelDocument, LabelObject,
                     LineObject, Prop, QRCodeObject, TextObject)
from ..printer import (NetworkPrinter, PrinterError, PrinterStatus, discover_printers, open_printer,
                       wait_for_completion)
from ..raster import build_job
from ..render import Placed, RenderResult, image_aspect, print_pages, render
from ..tapes import DPI, MM_PER_INCH, TAPES
from .canvas import LabelCanvas
from .panels import LabelPanel, PrintPanel, PropField, image_row, print_button
from .qtutil import (APP_NAME, COLOR_ERROR, COLOR_INFO, COLOR_OK, COLOR_WARN, HANDLE, MAX_IMAGE_PX, SHADE,
                     STATUS_INTERVAL_MS, BackgroundRunner, index_of, pil_to_qimage, rgb, set_color)

FILE_FILTER = "PT-Label-Etikett (*.ptlabel);;Alle Dateien (*)"
IMAGE_FILTER = "Bilder (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp);;Alle Dateien (*)"
INSERT_ITEMS = [("Text", "text"), ("QR-Code", "qrcode"), ("Barcode", "barcode"), ("Bild…", "image"),
                ("Rahmen", "frame"), ("Linie", "line")]
USAGE = (
    "• Objekte über die Werkzeugleiste oder „Einfügen“ hinzufügen.\n"
    "• Objekt anklicken und mit der Maus verschieben; das weiße Quadrat unten rechts ändert die Größe.\n"
    "• Pfeiltasten verschieben um 0,5 mm (mit Umschalt um 0,1 mm), Entf löscht.\n"
    "• Doppelklick springt in das Textfeld, Rechtsklick öffnet das Kontextmenü.\n"
    "• Mausrad scrollt, Strg+Mausrad zoomt.\n"
    "• Grau schattierte Bereiche werden nicht gedruckt (Bandrand und Ränder).\n"
    "• Die Vorschau zeigt die Farben des eingelegten Bandes.")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg = config.load()
        self.doc = LabelDocument()
        self.path: Path | None = None
        self.selected: LabelObject | None = None
        self.result: RenderResult | None = None
        self.status: PrinterStatus | None = None
        self.zoom = int(self.cfg.get("zoom") or 0)  # 0 = automatic
        self._drag: dict | None = None
        self._undo: list[str] = []
        self._undo_pos = -1
        self._saved_state = ""
        self._busy = False
        self._status_pending = False
        self._tape_checked = False
        self._fields: dict[str, PropField] = {}
        self._bg = BackgroundRunner(self)

        self._commit_timer = QTimer(self, singleShot=True, interval=500)
        self._commit_timer.timeout.connect(self.commit)
        self._render_timer = QTimer(self, singleShot=True, interval=0)
        self._render_timer.timeout.connect(self._render_now)
        self._status_timer = QTimer(self, interval=STATUS_INTERVAL_MS)
        self._status_timer.timeout.connect(self.refresh_status)

        fonts.REGISTRY.ensure_loaded()
        self._font_families = fonts.REGISTRY.families()
        self._build_ui()
        self.new_document(confirm=False)
        QTimer.singleShot(300, self._startup_printer)

    # ------------------------------------------------------------------ UI setup

    def _build_ui(self) -> None:
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(900, 520)
        self.resize(1280, 720)
        geometry = self.cfg.get("window_geometry")
        if geometry:
            self.restoreGeometry(QByteArray.fromBase64(geometry.encode("ascii")))

        self.canvas = LabelCanvas(self)
        self._build_actions()
        self._build_menu()
        self._build_toolbar()
        self._build_statusbar()

        side = QWidget()
        column = QVBoxLayout(side)
        self.label_panel = LabelPanel()
        self.label_panel.connect(self._on_label_panel)
        self.props_box = QGroupBox("Objekt")
        self.props_layout = QVBoxLayout(self.props_box)
        self._props_inner: QWidget | None = None
        self.print_panel = PrintPanel()
        self.print_panel.connect(self._on_print_panel)
        self.print_panel.printer.setText(self.cfg.get("printer", ""))
        self.print_panel.printer.editingFinished.connect(self._printer_changed)
        self.print_panel.search.clicked.connect(lambda: self.discover())
        self.print_panel.print.clicked.connect(self.print_label)
        column.addWidget(self.label_panel)
        column.addWidget(self.props_box)
        column.addWidget(self.print_panel)
        column.addStretch(1)
        side_scroll = QScrollArea()
        side_scroll.setWidget(side)
        side_scroll.setWidgetResizable(True)
        side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        side_scroll.setMinimumWidth(340)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.canvas.scroll)
        splitter.addWidget(side_scroll)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setCollapsible(0, False)
        splitter.setSizes([900, 360])
        self.setCentralWidget(splitter)

    def _action(self, text: str, slot, shortcut=None) -> QAction:
        action = QAction(text, self)
        action.triggered.connect(lambda checked=False: slot())
        if shortcut is not None:
            shortcuts = shortcut if isinstance(shortcut, list) else [shortcut]
            action.setShortcuts([QKeySequence(s) for s in shortcuts])
        return action

    def _build_actions(self) -> None:
        S = QKeySequence.StandardKey
        self.act_new = self._action("Neu", self.new_document, S.New)
        self.act_open = self._action("Öffnen…", self.open_document, S.Open)
        self.act_save = self._action("Speichern", self.save_document, S.Save)
        self.act_save_as = self._action("Speichern unter…", self.save_document_as, "Ctrl+Shift+S")
        self.act_export = self._action("Als PNG exportieren…", self.export_png)
        self.act_quit = self._action("Beenden", self.close, S.Quit)
        self.act_undo = self._action("Rückgängig", self.undo, S.Undo)
        self.act_redo = self._action("Wiederholen", self.redo, ["Ctrl+Y", "Ctrl+Shift+Z"])
        self.act_duplicate = self._action("Duplizieren", self.duplicate, "Ctrl+D")
        # Delete only acts while the canvas has the focus; text fields keep their own Delete key
        self.act_delete = self._action("Löschen", self.delete_selected, S.Delete)
        self.act_delete.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        self.canvas.addAction(self.act_delete)
        self.act_front = self._action("Nach vorne", lambda: self.restack(1))
        self.act_back = self._action("Nach hinten", lambda: self.restack(-1))
        self.act_center = self._action("Vertikal zentrieren", self.center_vertically)
        self.act_zoom_in = self._action("Vergrößern", lambda: self.set_zoom(self.current_zoom() + 1),
                                        ["Ctrl++", "Ctrl+="])
        self.act_zoom_out = self._action("Verkleinern", lambda: self.set_zoom(self.current_zoom() - 1), "Ctrl+-")
        self.act_zoom_auto = self._action("Automatisch", lambda: self.set_zoom(0))
        self.act_print = self._action("Drucken", self.print_label, S.Print)
        self.act_status = self._action("Status abfragen", lambda: self.refresh_status(manual=True))
        self.act_discover = self._action("Drucker suchen…", self.discover)

    def _build_menu(self) -> None:
        bar = self.menuBar()
        file = bar.addMenu("&Datei")
        file.addActions([self.act_new, self.act_open, self.act_save, self.act_save_as])
        file.addSeparator()
        file.addAction(self.act_export)
        file.addSeparator()
        file.addAction(self.act_quit)

        edit = bar.addMenu("&Bearbeiten")
        edit.addActions([self.act_undo, self.act_redo])
        edit.addSeparator()
        self._fill_object_menu(edit)

        insert = bar.addMenu("&Einfügen")
        for label, kind in INSERT_ITEMS:
            insert.addAction(self._action(label, lambda k=kind: self.insert(k)))

        view = bar.addMenu("&Ansicht")
        view.addActions([self.act_zoom_in, self.act_zoom_out, self.act_zoom_auto])

        printer = bar.addMenu("D&rucker")
        printer.addActions([self.act_print, self.act_status, self.act_discover])

        help_menu = bar.addMenu("&Hilfe")
        help_menu.addAction(self._action("Platzhalter…", lambda: QMessageBox.information(
            self, "Platzhalter", "In Texten, QR-Codes und Barcodes verwendbar:\n\n" + PLACEHOLDER_HELP)))
        help_menu.addAction(self._action("Bedienung…", lambda: QMessageBox.information(self, APP_NAME, USAGE)))
        help_menu.addAction(self._action("Über…", lambda: QMessageBox.about(
            self, APP_NAME, f"{APP_NAME} {__version__}\nEtiketten-Editor für Brother PT-P750W")))

        self.context_menu = QMenu(self)
        self._fill_object_menu(self.context_menu)

    def _fill_object_menu(self, menu: QMenu) -> None:
        menu.addActions([self.act_duplicate, self.act_delete])
        menu.addSeparator()
        menu.addActions([self.act_front, self.act_back, self.act_center])

    def _build_toolbar(self) -> None:
        bar = QToolBar("Werkzeuge")
        bar.setMovable(False)
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.addToolBar(bar)
        bar.addAction(self._action("Neu", self.new_document))
        bar.addAction(self._action("Öffnen", self.open_document))
        bar.addAction(self._action("Speichern", self.save_document))
        bar.addSeparator()
        for label, kind in INSERT_ITEMS:
            bar.addAction(self._action("+ " + label.rstrip("…"), lambda k=kind: self.insert(k)))
        bar.addSeparator()
        bar.addAction(self._action("Duplizieren", self.duplicate))
        bar.addAction(self._action("Löschen", self.delete_selected))
        bar.addSeparator()
        bar.addAction(self._action("−", lambda: self.set_zoom(self.current_zoom() - 1)))
        self.lbl_zoom = QLabel()
        self.lbl_zoom.setMinimumWidth(60)
        self.lbl_zoom.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bar.addWidget(self.lbl_zoom)
        bar.addAction(self._action("+", lambda: self.set_zoom(self.current_zoom() + 1)))
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bar.addWidget(spacer)
        button = print_button()
        button.clicked.connect(self.print_label)
        bar.addWidget(button)

    def _build_statusbar(self) -> None:
        bar = self.statusBar()
        self.lbl_printer = QLabel("Drucker: –")
        self.btn_adopt = QPushButton("Band übernehmen")
        self.btn_adopt.clicked.connect(self.adopt_tape)
        self.btn_adopt.hide()
        self.lbl_message = QLabel()
        self.lbl_warning = QLabel()
        set_color(self.lbl_warning, COLOR_WARN)
        self.lbl_size = QLabel()
        bar.addWidget(self.lbl_printer)
        bar.addWidget(self.btn_adopt)
        bar.addWidget(self.lbl_message, 1)
        bar.addPermanentWidget(self.lbl_warning)
        bar.addPermanentWidget(self.lbl_size)

    # ------------------------------------------------------------------ document state

    def new_document(self, confirm: bool = True) -> None:
        if confirm and not self._confirm_discard():
            return
        tape_mm = self.status.tape.width_mm if self.status and self.status.tape else 12.0
        self.doc = LabelDocument(tape_mm=tape_mm)
        self.doc.objects.append(TextObject(x=self.doc.margin_mm, font=fonts.REGISTRY.default_family()))
        self.path = None
        self._load_state()
        self.select(self.doc.objects[0])

    def _load_state(self) -> None:
        state = self.doc.to_json()
        self._undo = [state]
        self._undo_pos = 0
        self._saved_state = state
        self.selected = None
        self._sync_label_panel()
        self._sync_print_panel()
        self._build_props()
        self._update_tape_warning()
        self._update_title()
        self.redraw()

    def _is_modified(self) -> bool:
        return self.doc.to_json() != self._saved_state

    def _is_pristine(self) -> bool:
        return self.path is None and len(self._undo) == 1 and not self._is_modified()

    def _confirm_discard(self) -> bool:
        self._flush_commit()
        if not self._is_modified():
            return True
        B = QMessageBox.StandardButton
        answer = QMessageBox.question(self, APP_NAME, "Das Etikett wurde geändert. Änderungen speichern?",
                                      B.Yes | B.No | B.Cancel, B.Yes)
        if answer == B.Cancel:
            return False
        return self.save_document() if answer == B.Yes else True

    def _update_title(self) -> None:
        name = self.path.name if self.path else "Unbenannt"
        self.setWindowTitle(f"{'*' if self._is_modified() else ''}{name} – {APP_NAME}")

    def changed(self) -> None:
        """Call after every modification of the document."""
        self.redraw()
        self._commit_timer.start()

    def commit(self) -> None:
        self._commit_timer.stop()
        state = self.doc.to_json()
        if self._undo[self._undo_pos] != state:
            del self._undo[self._undo_pos + 1:]
            self._undo.append(state)
            if len(self._undo) > 200:
                del self._undo[0]
            self._undo_pos = len(self._undo) - 1
        self._update_title()

    def _flush_commit(self) -> None:
        if self._commit_timer.isActive():
            self.commit()

    def undo(self) -> None:
        self._flush_commit()
        if self._undo_pos > 0:
            self._undo_pos -= 1
            self._restore(self._undo[self._undo_pos])

    def redo(self) -> None:
        self._flush_commit()
        if self._undo_pos < len(self._undo) - 1:
            self._undo_pos += 1
            self._restore(self._undo[self._undo_pos])

    def _restore(self, state: str) -> None:
        index = index_of(self.doc.objects, self.selected)
        self.doc = LabelDocument.from_json(state)
        self.selected = self.doc.objects[index] if index is not None and index < len(self.doc.objects) else None
        self._sync_label_panel()
        self._sync_print_panel()
        self._build_props()
        self._update_tape_warning()
        self._update_title()
        self.redraw()

    # ------------------------------------------------------------------ files

    def _initial_dir(self) -> str:
        if self.path:
            return str(self.path.parent)
        return self.cfg.get("last_dir") or str(Path.home())

    def open_document(self) -> None:
        if not self._confirm_discard():
            return
        name, _ = QFileDialog.getOpenFileName(self, "Etikett öffnen", self._initial_dir(), FILE_FILTER)
        if not name:
            return
        try:
            doc = LabelDocument.load(name)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            QMessageBox.critical(self, APP_NAME, f"Datei kann nicht geöffnet werden:\n{exc}")
            return
        self.doc = doc
        self.path = Path(name)
        self.cfg["last_dir"] = str(self.path.parent)
        self._load_state()

    def save_document(self) -> bool:
        if self.path is None:
            return self.save_document_as()
        self._flush_commit()
        try:
            self.doc.save(self.path)
        except OSError as exc:
            QMessageBox.critical(self, APP_NAME, f"Speichern fehlgeschlagen:\n{exc}")
            return False
        self._saved_state = self.doc.to_json()
        self._update_title()
        self._set_message(f"Gespeichert: {self.path.name}", COLOR_OK)
        return True

    def _ask_save_name(self, title: str, file_filter: str, suffix: str) -> Path | None:
        name, _ = QFileDialog.getSaveFileName(self, title, self._initial_dir(), file_filter)
        if not name:
            return None
        path = Path(name)
        return path if path.suffix else path.with_suffix(suffix)

    def save_document_as(self) -> bool:
        path = self._ask_save_name("Etikett speichern", FILE_FILTER, ".ptlabel")
        if path is None:
            return False
        self.path = path
        self.cfg["last_dir"] = str(self.path.parent)
        return self.save_document()

    def export_png(self) -> None:
        path = self._ask_save_name("Als PNG exportieren", "PNG (*.png)", ".png")
        if path is None:
            return
        res = render(self.doc)
        tape_rgb, ink_rgb = self._preview_colors()
        img = Image.new("RGB", res.image.size, tape_rgb)
        img.paste(ink_rgb, (0, 0), res.image)
        img = img.resize((img.width * 4, img.height * 4), Image.Resampling.NEAREST)
        try:
            img.save(path, dpi=(DPI * 4, DPI * 4))
        except OSError as exc:
            QMessageBox.critical(self, APP_NAME, f"Export fehlgeschlagen:\n{exc}")
            return
        self._set_message(f"Exportiert: {path.name}", COLOR_OK)

    def closeEvent(self, event) -> None:
        if not self._confirm_discard():
            event.ignore()
            return
        self.cfg.pop("geometry", None)  # Tk geometry string of older versions
        self.cfg["window_geometry"] = bytes(self.saveGeometry().toBase64()).decode("ascii")
        self.cfg["zoom"] = self.zoom
        self.cfg["printer"] = self.print_panel.printer.text().strip()
        config.save(self.cfg)
        event.accept()

    # ------------------------------------------------------------------ panels

    def _sync_label_panel(self) -> None:
        panel, doc = self.label_panel, self.doc
        blockers = [QSignalBlocker(w) for w in (panel.tape, panel.auto_length, panel.length, panel.margin)]
        panel.tape.setCurrentText(doc.tape.label)
        panel.auto_length.setChecked(doc.auto_length)
        panel.length.setValue(doc.length_mm)
        panel.margin.setValue(doc.margin_mm)
        for blocker in blockers:
            blocker.unblock()
        panel.length.setEnabled(not doc.auto_length)
        panel.print_area.setText(f"Druckbereich: {doc.tape.print_mm:.1f} mm hoch")

    def _on_label_panel(self, *_) -> None:
        panel, doc = self.label_panel, self.doc
        tape = next((t for t in TAPES if t.label == panel.tape.currentText()), doc.tape)
        doc.tape_mm = tape.width_mm
        auto = panel.auto_length.isChecked()
        if doc.auto_length and not auto and self.result:
            doc.length_mm = round(self.result.length_mm, 1)  # start from the current length
            with QSignalBlocker(panel.length):
                panel.length.setValue(doc.length_mm)
        doc.auto_length = auto
        doc.length_mm = panel.length.value()
        doc.margin_mm = panel.margin.value()
        panel.length.setEnabled(not doc.auto_length)
        panel.print_area.setText(f"Druckbereich: {doc.tape.print_mm:.1f} mm hoch")
        self._update_tape_warning()
        self.changed()

    def _sync_print_panel(self) -> None:
        panel = self.print_panel
        widgets = [panel.copies, panel.counter, *panel.flags.values()]
        blockers = [QSignalBlocker(w) for w in widgets]
        panel.copies.setValue(self.doc.copies)
        panel.counter.setValue(self.doc.counter_start)
        for attr, box in panel.flags.items():
            box.setChecked(bool(getattr(self.doc, attr)))
        for blocker in blockers:
            blocker.unblock()

    def _on_print_panel(self, *_) -> None:
        panel = self.print_panel
        self.doc.copies = panel.copies.value()
        self.doc.counter_start = panel.counter.value()
        for attr, box in panel.flags.items():
            setattr(self.doc, attr, box.isChecked())
        self.changed()

    def _build_props(self) -> None:
        if self._props_inner is not None:
            self.props_layout.removeWidget(self._props_inner)
            self._props_inner.hide()
            self._props_inner.deleteLater()
        self._fields = {}
        inner = QWidget()
        self._props_inner = inner
        self.props_layout.addWidget(inner)
        grid = QGridLayout(inner)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setColumnStretch(1, 1)
        obj = self.selected
        if obj is None:
            self.props_box.setTitle("Objekt")
            hint = QLabel("Kein Objekt ausgewählt.\nObjekt anklicken oder über „Einfügen“\nein neues hinzufügen.")
            set_color(hint, COLOR_INFO)
            grid.addWidget(hint, 0, 0)
            return
        self.props_box.setTitle(obj.title)
        row = 0
        for prop in obj.props():
            row = self._add_prop_widget(grid, obj, prop, row)
        self._update_prop_states()
        self._show_effective_size()

    def _add_prop_widget(self, grid: QGridLayout, obj: LabelObject, prop: Prop, row: int) -> int:
        if prop.kind == "image":
            grid.addLayout(image_row(getattr(obj, "name", ""), self.load_image_for_selected), row, 0, 1, 2)
            return row + 1
        value = getattr(obj, prop.attr)
        if prop.kind == "font":
            value = fonts.REGISTRY.find_family(value or "") or fonts.REGISTRY.default_family()
        field = PropField(prop, value, self._font_families)
        field.setParent(self._props_inner)
        field.changed.connect(lambda p=prop, f=field: self._on_prop_field(p, f))
        if prop.kind == "multiline":
            grid.addWidget(QLabel(prop.label), row, 0, 1, 2)
            grid.addWidget(field.widget, row + 1, 0, 1, 2)
            row += 2
        elif prop.kind == "bool":
            grid.addWidget(field.widget, row, 0, 1, 2)
            row += 1
        else:
            grid.addWidget(QLabel(prop.label), row, 0)
            grid.addWidget(field.widget, row, 1)
            row += 1
        self._fields[prop.attr] = field
        return row

    def _on_prop_field(self, prop: Prop, field: PropField) -> None:
        obj = self.selected
        if obj is None:
            return
        value = field.value()
        if prop.kind == "multiline":
            if getattr(obj, prop.attr) == value:
                return
        elif prop.kind == "int":
            value = int(round(value))
        elif prop.kind == "choice":
            if value is None:
                return
        elif prop.kind == "font":
            value = fonts.REGISTRY.find_family(value)
            if value is None:
                return
        if isinstance(obj, TextObject) and (prop.attr == "size" or (prop.attr == "auto_size" and not value)):
            self._freeze_auto_text(obj)
        setattr(obj, prop.attr, value)
        if isinstance(obj, ImageObject) and obj.keep_aspect and prop.attr in ("width", "height", "keep_aspect"):
            aspect = image_aspect(obj)
            if aspect:
                if prop.attr == "height":
                    obj.width = round(obj.height * aspect, 1)
                else:
                    obj.height = round(obj.width / aspect, 1)
                self._sync_props(("width", "height"))
        self._update_prop_states()
        self.changed()

    def _sync_props(self, attrs=None) -> None:
        obj = self.selected
        if obj is None:
            return
        for attr, field in self._fields.items():
            if not attrs or attr in attrs:
                field.set_value(getattr(obj, attr))

    def _update_prop_states(self) -> None:
        obj = self.selected
        rules = []
        if isinstance(obj, ImageObject):
            rules.append(("threshold", not obj.dither))
        if isinstance(obj, BarcodeObject):
            rules.append(("text_size", obj.show_text))
        if isinstance(obj, TextObject):
            rules.append(("y", not obj.auto_size))
        for attr, enabled in rules:
            field = self._fields.get(attr)
            if field is not None:
                field.widget.setEnabled(enabled)

    def _freeze_auto_text(self, obj: TextObject) -> None:
        """Turn an automatically sized text into a fixed one at its current size and position."""
        placed = self._placed_of(obj)
        if obj.auto_size and placed and self.result:
            obj.size = placed.size_pt or obj.size
            obj.y = round(placed.box[1] / self.result.scale, 2)
            obj.auto_size = False
            self._sync_props(("y", "auto_size"))
            self._update_prop_states()

    # ------------------------------------------------------------------ objects

    def select(self, obj: LabelObject | None) -> None:
        if obj is not self.selected:
            self.selected = obj
            self._build_props()
        self._draw_selection()

    def _placed_of(self, obj) -> Placed | None:
        if self.result is None or obj is None:
            return None
        return next((p for p in self.result.placed if p.obj is obj), None)

    def _next_x(self) -> float:
        if not self.result or not self.result.placed:
            return self.doc.margin_mm
        right = max(p.box[2] for p in self.result.placed) / self.result.scale
        return round(right + 1.5, 1)

    def insert(self, kind: str) -> None:
        doc = self.doc
        tape = doc.tape
        top = round(tape.band_top_mm, 2)
        band = round(tape.print_mm, 1)
        x = self._next_x()
        if kind == "text":
            obj = TextObject(x=x, y=top, font=fonts.REGISTRY.default_family())
        elif kind == "qrcode":
            obj = QRCodeObject(x=x, y=top, size=band)
        elif kind == "barcode":
            obj = BarcodeObject(x=x, y=top, height=band, show_text=band >= 6)
        elif kind == "image":
            obj = self._image_object_from_dialog(x, top, band)
            if obj is None:
                return
        elif kind == "frame":
            length = (self.result.length_mm if self.result else 40) - 2 * doc.margin_mm
            obj = FrameObject(x=doc.margin_mm, y=top, width=round(max(5.0, length), 1), height=band)
        else:
            obj = LineObject(x=x, y=round(top + band / 2 - 0.2, 2), length=20)
        doc.objects.append(obj)
        self.select(obj)
        self.changed()
        self.commit()

    def _read_image_dialog(self):
        name, _ = QFileDialog.getOpenFileName(self, "Bild laden", self._initial_dir(), IMAGE_FILTER)
        if not name:
            return None
        try:
            img = Image.open(name)
            img.load()
        except OSError as exc:
            QMessageBox.critical(self, APP_NAME, f"Bild kann nicht geladen werden:\n{exc}")
            return None
        img.thumbnail((MAX_IMAGE_PX, MAX_IMAGE_PX))
        if img.mode not in ("1", "L", "LA", "RGB", "RGBA"):
            img = img.convert("RGBA")
        buffer = io.BytesIO()
        img.save(buffer, "PNG")
        return base64.b64encode(buffer.getvalue()).decode("ascii"), Path(name).name, img.width / img.height

    def _image_object_from_dialog(self, x: float, y: float, height: float) -> ImageObject | None:
        loaded = self._read_image_dialog()
        if loaded is None:
            return None
        data, name, aspect = loaded
        return ImageObject(x=x, y=y, data=data, name=name, height=height, width=round(height * aspect, 1))

    def load_image_for_selected(self) -> None:
        obj = self.selected
        if not isinstance(obj, ImageObject):
            return
        loaded = self._read_image_dialog()
        if loaded is None:
            return
        obj.data, obj.name, aspect = loaded
        if obj.keep_aspect:
            obj.width = round(obj.height * aspect, 1)
        self._build_props()
        self.changed()
        self.commit()

    def delete_selected(self) -> None:
        index = index_of(self.doc.objects, self.selected)
        if index is None:
            return
        del self.doc.objects[index]
        self.select(None)
        self.changed()
        self.commit()

    def duplicate(self) -> None:
        if self.selected is None:
            return
        copy = self.selected.copy()
        copy.x += 2
        if not (isinstance(copy, TextObject) and copy.auto_size):
            copy.y += 1
        self.doc.objects.append(copy)
        self.select(copy)
        self.changed()
        self.commit()

    def restack(self, direction: int) -> None:
        objects = self.doc.objects
        index = index_of(objects, self.selected)
        if index is None:
            return
        target = max(0, min(len(objects) - 1, index + direction))
        objects.insert(target, objects.pop(index))
        self.changed()

    def center_vertically(self) -> None:
        obj, placed = self.selected, self._placed_of(self.selected)
        if obj is None or placed is None or (isinstance(obj, TextObject) and obj.auto_size):
            return
        top, bottom = self.result.band
        height = placed.box[3] - placed.box[1]
        obj.y = round((top + (bottom - top - height) / 2) / self.result.scale, 2)
        self._sync_props(("y",))
        self.changed()

    def nudge(self, dx: float, dy: float) -> None:
        obj = self.selected
        if obj is not None:
            obj.x = round(obj.x + dx, 2)
            if not (isinstance(obj, TextObject) and obj.auto_size):
                obj.y = round(obj.y + dy, 2)
            self._sync_props(("x", "y"))
            self.changed()

    # ------------------------------------------------------------------ canvas

    def current_zoom(self) -> int:
        if self.zoom > 0:
            return self.zoom
        tape_px = round(self.doc.tape.width_mm * DPI / MM_PER_INCH)
        return max(1, min(10, round(260 / tape_px)))

    def set_zoom(self, zoom: int) -> None:
        self.zoom = 0 if zoom == 0 else max(1, min(12, zoom))
        self.redraw()

    def redraw(self) -> None:
        if not self._render_timer.isActive():
            self._render_timer.start()

    def _preview_colors(self):
        tape = self.status.tape_color_rgb if self.status else None
        ink = self.status.text_color_rgb if self.status else None
        return rgb(tape or "#ffffff"), rgb(ink or "#111111")

    def _render_now(self) -> None:
        self._render_timer.stop()
        try:
            res = render(self.doc)
        except Exception as exc:
            self._set_message(f"Fehler bei der Darstellung: {exc}", COLOR_ERROR)
            return
        self.result = res
        z = self.current_zoom()
        self.lbl_zoom.setText(f"{z}×" + ("" if self.zoom else " auto"))

        tape_rgb, ink_rgb = self._preview_colors()
        mask = res.image
        img = Image.new("RGB", mask.size, tape_rgb)
        img.paste(ink_rgb, (0, 0), mask)
        shade = Image.new("L", mask.size, 0)
        draw = ImageDraw.Draw(shade)
        w, h = mask.size
        top, bottom = res.band
        if top > 0:
            draw.rectangle((0, 0, w - 1, top - 1), fill=110)
        if bottom < h:
            draw.rectangle((0, bottom, w - 1, h - 1), fill=110)
        m = res.margin_px
        if m > 0:
            draw.rectangle((0, top, m - 1, bottom - 1), fill=70)
            draw.rectangle((w - m, top, w - 1, bottom - 1), fill=70)
        img.paste(SHADE, (0, 0), shade)
        self.canvas.set_image(pil_to_qimage(img), res, z)
        self._draw_selection()

        self.lbl_size.setText(f"{res.tape.label} × {res.length_mm:.1f} mm")
        self.lbl_warning.setText(" · ".join(dict.fromkeys(res.warnings)))
        self._show_effective_size()

    def _show_effective_size(self) -> None:
        """Show the computed size of an auto-sized text without touching the document."""
        sel, field = self.selected, self._fields.get("size")
        if isinstance(sel, TextObject) and sel.auto_size and field:
            placed = self._placed_of(sel)
            if placed and placed.size_pt:
                field.set_value(placed.size_pt)

    def _draw_selection(self) -> None:
        placed = self._placed_of(self.selected)
        self.canvas.set_selection(placed.box if placed else None)

    def _hit(self, px: float, py: float) -> LabelObject | None:
        """Smallest object under the cursor; empty frames only react to their outline."""
        z = self.current_zoom()
        tolerance = 3 / z
        best = None
        for placed in reversed(self.result.placed if self.result else []):
            x0, y0, x1, y1 = placed.box
            if not (x0 - tolerance <= px <= x1 + tolerance and y0 - tolerance <= py <= y1 + tolerance):
                continue
            obj = placed.obj
            if isinstance(obj, FrameObject) and not obj.fill:
                edge = obj.thickness * self.result.scale + 4 / z
                if min(px - x0, x1 - px, py - y0, y1 - py) > edge:
                    continue
            area = (x1 - x0) * (y1 - y0)
            if best is None or area < best[0]:
                best = (area, obj)
        return best[1] if best else None

    def on_press(self, px: float, py: float) -> None:
        if self.result is None:
            return
        placed = self._placed_of(self.selected)
        grip = (HANDLE / 2 + 2) / self.current_zoom()
        if placed and abs(px - placed.box[2]) <= grip and abs(py - placed.box[3]) <= grip:
            obj = self.selected
            if isinstance(obj, TextObject):
                self._freeze_auto_text(obj)
            size = (max(1, placed.box[2] - placed.box[0]), max(1, placed.box[3] - placed.box[1]))
            self._drag = {"mode": "resize", "obj": obj, "start": (px, py), "orig": obj.copy(), "size": size,
                          "moved": False}
            return
        hit = self._hit(px, py)
        self.select(hit)
        if hit is not None:
            self._drag = {"mode": "move", "obj": hit, "start": (px, py), "orig": (hit.x, hit.y), "moved": False}

    def on_motion(self, px: float, py: float) -> None:
        drag = self._drag
        if not drag or self.result is None:
            return
        dx, dy = px - drag["start"][0], py - drag["start"][1]
        z = self.current_zoom()
        if not drag["moved"] and abs(dx) * z < 3 and abs(dy) * z < 3:
            return
        drag["moved"] = True
        obj, scale = drag["obj"], self.result.scale
        if drag["mode"] == "move":
            obj.x = round(drag["orig"][0] + dx / scale, 1)
            if not (isinstance(obj, TextObject) and obj.auto_size):
                obj.y = round(drag["orig"][1] + dy / scale, 1)
            self._sync_props(("x", "y"))
        else:
            w0, h0 = drag["size"]
            fx, fy = max(1.0, w0 + dx) / w0, max(1.0, h0 + dy) / h0
            if obj.rotation % 180:
                fx, fy = fy, fx
            obj.resize(drag["orig"], fx, fy)
            self._sync_props()
        self.redraw()

    def on_release(self) -> None:
        drag, self._drag = self._drag, None
        if drag and drag["moved"]:
            self.changed()
            self.commit()

    def on_double(self) -> None:
        if self.selected is None:
            return
        for attr in ("text", "data"):
            field = self._fields.get(attr)
            if field is not None and field.prop.kind in ("multiline", "text"):
                field.widget.setFocus()
                field.widget.selectAll()
                return

    def on_context(self, px: float, py: float, global_pos) -> None:
        if self.result is None:
            return
        hit = self._hit(px, py)
        if hit is not None:
            self.select(hit)
            self.context_menu.exec(global_pos)

    # ------------------------------------------------------------------ printer

    def _set_message(self, text: str, color: str = COLOR_INFO) -> None:
        self.lbl_message.setText(text)
        set_color(self.lbl_message, color)

    def _printer_target(self) -> str:
        return self.print_panel.printer.text().strip()

    def _printer_changed(self) -> None:
        target = self._printer_target()
        if target != self.cfg.get("printer", ""):
            self.cfg["printer"] = target
            config.save(self.cfg)
            self.status = None
            self.refresh_status(manual=True)

    def _startup_printer(self) -> None:
        if self._printer_target():
            self._start_periodic_status()
        else:
            self.discover(silent=True, then=self._start_periodic_status)

    def _start_periodic_status(self) -> None:
        self.refresh_status()
        self._status_timer.start()

    def refresh_status(self, manual: bool = False) -> None:
        target = self._printer_target()
        if not target:
            self._show_printer_text("Kein Drucker eingestellt – Drucker einschalten und „Suchen…“ klicken "
                                    "oder Hostname/IP eintragen", COLOR_WARN)
            return
        if self._status_pending or self._busy:
            return
        self._status_pending = True
        if manual:
            self._show_printer_text(f"Frage {target} ab …", COLOR_INFO)

        def done(status, error):
            self._status_pending = False
            if error is not None:
                had_status = self.status is not None
                self.status = None
                self._show_printer_text(str(error), COLOR_ERROR)
                self._update_tape_warning()
                if had_status:
                    self.redraw()
                return
            self._apply_status(status)

        self._bg.run(lambda: open_printer(target).status(), done)

    def _show_printer_text(self, text: str, color: str) -> None:
        self.print_panel.status.setText(text)
        set_color(self.print_panel.status, color)
        self.lbl_printer.setText(text if len(text) < 70 else text[:67] + "…")
        set_color(self.lbl_printer, color)

    def _apply_status(self, status: PrinterStatus) -> None:
        old = self.status
        self.status = status
        self._show_printer_text(f"{status.model}: {status.summary()}", COLOR_ERROR if status.errors else COLOR_OK)
        if not self._tape_checked and status.tape:
            self._tape_checked = True
            if self._is_pristine() and status.tape.width_mm != self.doc.tape_mm:
                self.doc.tape_mm = status.tape.width_mm
                self._load_state()
                self.select(self.doc.objects[0] if self.doc.objects else None)
        self._update_tape_warning()
        if old is None or (old.tape_color, old.text_color) != (status.tape_color, status.text_color):
            self.redraw()

    def _update_tape_warning(self) -> None:
        tape = self.status.tape if self.status else None
        if tape and tape.code != self.doc.tape.code:
            self.btn_adopt.setText(f"Eingelegtes Band ({tape.label}) übernehmen")
            self.btn_adopt.show()
        else:
            self.btn_adopt.hide()

    def adopt_tape(self) -> None:
        if self.status and self.status.tape:
            self.doc.tape_mm = self.status.tape.width_mm
            self._sync_label_panel()
            self._update_tape_warning()
            self.changed()

    def discover(self, silent: bool = False, then=None) -> None:
        if not silent:
            self._set_message("Suche Brother-Drucker im Netzwerk …")

        def done(found, error):
            self._set_message("")
            found = found or []
            label_printers = [p for p in found if p.model.upper().startswith(("PT", "QL"))]
            if error is not None and not silent:
                QMessageBox.critical(self, APP_NAME, f"Suche fehlgeschlagen:\n{error}")
            elif len(label_printers) == 1:
                self._use_printer(label_printers[0].address)
            elif found and not silent:
                self._choose_printer(found)
            elif not silent:
                QMessageBox.information(self, APP_NAME, "Kein Brother-Drucker gefunden.\n"
                                                        "Bitte Hostname oder IP-Adresse von Hand eintragen.")
            if then:
                then()

        self._bg.run(lambda: discover_printers(2.0), done)

    def _use_printer(self, address: str) -> None:
        self.print_panel.printer.setText(address)
        self._printer_changed()

    def _choose_printer(self, printers) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Drucker auswählen")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Gefundene Brother-Drucker:"))
        listbox = QListWidget()
        listbox.addItems([f"{p.model}  {p.address}  ({p.ip})" for p in printers])
        listbox.setCurrentRow(0)
        listbox.itemDoubleClicked.connect(dialog.accept)
        layout.addWidget(listbox)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Übernehmen")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.resize(480, 260)
        if dialog.exec() == QDialog.DialogCode.Accepted and listbox.currentRow() >= 0:
            self._use_printer(printers[listbox.currentRow()].address)

    def print_label(self) -> None:
        if self._busy:
            return
        self._flush_commit()
        target = self._printer_target()
        if not target:
            if QMessageBox.question(self, APP_NAME, "Es ist kein Drucker eingestellt. Jetzt im Netzwerk suchen?") \
                    == QMessageBox.StandardButton.Yes:
                self.discover()
            return
        doc = self.doc
        tape = self.status.tape if self.status else None
        if tape and tape.code != doc.tape.code and QMessageBox.question(
                self, APP_NAME, f"Im Drucker ist {tape.label}-Band eingelegt, das Etikett ist für {doc.tape.label} "
                                "angelegt.\n\nTrotzdem drucken?") != QMessageBox.StandardButton.Yes:
            return
        try:
            pages = print_pages(doc)
            job = build_job(pages, doc.tape, doc.print_options())
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, f"Etikett kann nicht erzeugt werden:\n{exc}")
            return
        self._busy = True
        self._set_message(f"Sende {len(pages)} Etikett(en) an {target} …")

        def work():
            printer = open_printer(target)
            printer.send(job)
            if not isinstance(printer, NetworkPrinter):
                return None
            try:
                return wait_for_completion(printer)
            except PrinterError:  # job was sent, only the follow-up status failed
                return None

        def done(status, error):
            self._busy = False
            if error is not None:
                self._set_message("Druck fehlgeschlagen", COLOR_ERROR)
                QMessageBox.critical(self, APP_NAME, f"Druck fehlgeschlagen:\n{error}")
                return
            if status is not None:
                self._apply_status(status)
            if status is not None and status.errors:
                self._set_message("Drucker meldet Fehler", COLOR_ERROR)
                QMessageBox.critical(self, APP_NAME, "Der Drucker meldet:\n" + "\n".join(status.errors))
            else:
                self._set_message(f"{len(pages)} Etikett(en) gedruckt", COLOR_OK)

        self._bg.run(work, done)
