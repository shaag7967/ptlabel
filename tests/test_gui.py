import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from PySide6.QtCore import QEvent, QObject, QPoint, Qt
    from PySide6.QtTest import QTest
except ImportError:  # pragma: no cover
    QTest = None

if QTest is not None:
    from ptlabel import webfonts
    from ptlabel.gui import create_app, fontui, printing
    from ptlabel.gui.document import DocumentController, UndoHistory
    from ptlabel.gui.snapping import snap
    from ptlabel.gui.theme import ThemeManager
    from ptlabel.gui.window import MainWindow
    from ptlabel.model import LabelDocument, TextObject
    from ptlabel.printer import PrinterStatus
    from ptlabel.render import render

# status block of a PT-P750W with 12 mm yellow/black tape (see test_core.py)
REAL_STATUS = bytes.fromhex("80 20 42 30 68 30 04 00 00 00 0c 01 00 00 00 00"
                            "00 00 00 00 00 00 00 00 06 08 00 00 00 00 00 00")


@unittest.skipIf(QTest is None, "PySide6 not installed")
class DocumentControllerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()

    def setUp(self):
        self.doc = DocumentController()
        self.doc.new()
        self.doc.render_now()

    def add(self, kind):
        self.doc.add_object(self.doc.create_object(kind))
        self.doc.render_now()
        return self.doc.selected

    def test_undo_history(self):
        history = UndoHistory("a")
        self.assertFalse(history.push("a"))
        self.assertTrue(history.push("b"))
        self.assertEqual(history.undo(), "a")
        self.assertEqual(history.redo(), "b")
        self.assertIsNone(history.redo())

    def test_insert_undo_redo(self):
        for kind in ("text", "qrcode", "barcode", "frame", "line"):
            self.add(kind)
        self.assertEqual(len(self.doc.doc.objects), 6)
        self.doc.undo()
        self.assertEqual(len(self.doc.doc.objects), 5)
        self.doc.redo()
        self.assertEqual(len(self.doc.doc.objects), 6)
        self.assertTrue(self.doc.is_modified())

    def test_new_objects_do_not_overlap(self):
        qr = self.add("qrcode")
        text_box = self.doc.result.placed[0].box
        self.assertGreater(self.doc.placed_of(qr).box[0], text_box[2])

    def test_margin_change_moves_objects(self):
        qr = self.add("qrcode")
        text = self.doc.doc.objects[0]
        x_text, x_qr = text.x, qr.x
        self.doc.set_label(margin_mm=5)
        self.assertAlmostEqual(text.x, x_text + 3)
        self.assertAlmostEqual(qr.x, x_qr + 3)
        self.doc.render_now()
        self.assertEqual(self.doc.placed_of(text).box[0], self.doc.result.margin_px)

    def test_reorder_and_restack(self):
        qr = self.add("qrcode")
        text = self.doc.doc.objects[0]
        self.doc.reorder([qr, text])
        self.assertIs(self.doc.doc.objects[-1], text)
        self.doc.select(qr)
        self.doc.restack(1)
        self.assertIs(self.doc.doc.objects[-1], qr)

    def test_center_horizontally_follows_the_label(self):
        text = self.doc.doc.objects[0]
        self.doc.set_label(auto_length=False, length_mm=60)
        self.doc.select(text)
        self.doc.center_horizontally()
        self.doc.render_now()
        x0, _, x1, _ = self.doc.placed_of(text).box
        width = self.doc.result.image.width
        self.assertAlmostEqual((x0 + x1) / 2, width / 2, delta=1)
        self.doc.set_property(text, "text", "A much longer text")  # stays centered
        self.doc.render_now()
        x0, _, x1, _ = self.doc.placed_of(text).box
        self.assertAlmostEqual((x0 + x1) / 2, width / 2, delta=1)
        self.doc.set_property(text, "h_align", "free")  # back to free: keeps its place
        self.assertAlmostEqual(text.x, x0 / self.doc.result.scale, places=1)
        self.doc.set_property(text, "h_align", "right")
        self.doc.render_now()
        self.assertEqual(self.doc.placed_of(text).box[2], width - self.doc.result.margin_px)

    def test_changing_barcode_type_keeps_valid_data(self):
        code = self.add("barcode")
        self.doc.set_property(code, "symbology", "ean13")
        self.assertEqual(code.data, "400638133393")
        self.doc.set_property(code, "data", "123456789012")
        self.doc.set_property(code, "symbology", "code128")  # still valid: kept
        self.assertEqual(code.data, "123456789012")

    def test_editing_size_freezes_auto_text(self):
        text = self.doc.doc.objects[0]
        self.assertTrue(text.auto_size)
        self.doc.set_property(text, "size", 10)
        self.assertFalse(text.auto_size)
        self.assertEqual(text.size, 10)

    def test_save_and_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.ptlabel"
            self.doc.save(path)
            self.assertFalse(self.doc.is_modified())
            self.assertEqual(LabelDocument.load(path).to_json(), self.doc.doc.to_json())
            other = DocumentController()
            other.open(path)
            self.assertEqual(other.name, "t.ptlabel")


@unittest.skipIf(QTest is None, "PySide6 not installed")
class SnappingTest(unittest.TestCase):
    def test_snaps_to_tape_center_and_other_objects(self):
        result = render(LabelDocument(auto_length=False, length_mm=50))
        top, bottom = result.band
        center_y = (top + bottom) / 2
        dx, dy, guides = snap((100, center_y - 12, 140, center_y + 10), result, [], 5)
        self.assertEqual(dy, 1)
        self.assertTrue(any(not g.vertical and g.position == center_y for g in guides))
        dx, dy, guides = snap((203, 10, 230, 20), result, [(150, 0, 200, 5)], 5, snap_y=False)
        self.assertEqual((dx, dy), (-3, 0))
        self.assertEqual([g.position for g in guides if g.vertical], [200])

    def test_no_snap_outside_threshold(self):
        result = render(LabelDocument(auto_length=False, length_mm=50))
        self.assertEqual(snap((100, 1, 120, 3), result, [], 2), (0.0, 0.0, []))


@unittest.skipIf(QTest is None, "PySide6 not installed")
class MainWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.theme = ThemeManager(cls.app, "light")

    def setUp(self):
        patcher = mock.patch.object(printing, "discover_printers", return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.win = MainWindow(self.theme, {"printer": ""})
        self.addCleanup(self.win.deleteLater)
        self.win.resize(1300, 800)
        self.win.show()
        self.doc = self.win.document
        self.doc.render_now()

    def insert(self, kind):
        self.win.insert(kind)
        self.doc.render_now()
        return self.doc.selected

    def test_docks_and_toolbars(self):
        names = {dock.objectName() for dock in self.win.docks}
        self.assertEqual(names, {"properties_dock", "label_dock", "print_dock", "objects_dock"})
        self.assertGreaterEqual(self.win.properties_dock.width(), 300)
        self.win.reset_layout()
        self.assertFalse(any(dock.isFloating() for dock in self.win.docks))

    def test_no_stray_windows_when_selecting_objects(self):
        # a widget shown before it has a parent becomes a top-level window for a moment; on GNOME
        # this starts a startup notification with a busy cursor (seen with the barcode hint)
        shown = []

        class Spy(QObject):
            def eventFilter(self, obj, event):
                if event.type() == QEvent.Type.Show and obj.isWidgetType() and obj.isWindow():
                    shown.append(type(obj).__name__)
                return False

        spy = Spy()
        self.app.installEventFilter(spy)
        self.addCleanup(self.app.removeEventFilter, spy)
        for kind in ("text", "qrcode", "barcode", "frame", "line"):
            self.insert(kind)
        for row in range(self.win.objects_panel.list.count()):
            self.win.objects_panel.list.setCurrentRow(row)
        self.assertEqual(shown, [])

    def test_objects_panel_follows_document(self):
        qr = self.insert("qrcode")
        panel = self.win.objects_panel
        self.assertEqual(panel.list.count(), 2)
        self.assertIs(panel.list.currentItem().data(Qt.ItemDataRole.UserRole), qr)  # front first
        panel.list.setCurrentRow(1)
        self.assertIsInstance(self.doc.selected, TextObject)

    def test_format_toolbar_edits_text(self):
        text = self.doc.doc.objects[0]
        self.doc.select(text)
        bar = self.win.format_bar
        self.assertTrue(bar.bold.isEnabled())
        bar.bold.trigger()
        bar.align["center"].trigger()
        self.assertTrue(text.bold)
        self.assertEqual(text.align, "center")
        self.insert("qrcode")
        self.assertFalse(bar.bold.isEnabled())

    def test_format_toolbar_centers_text_on_label(self):
        text = self.doc.doc.objects[0]
        self.doc.select(text)
        self.win.format_bar.align["center"].trigger()
        self.assertEqual((text.align, text.h_align), ("center", "center"))
        self.assertFalse(self.win.properties._fields["x"].widget.isEnabled())
        self.win.format_bar.align["left"].trigger()
        self.assertEqual((text.align, text.h_align), ("left", "free"))

    def test_print_buttons_locked_while_printing(self):
        printer = self.win.printer
        button = self.win.print_panel.print_button
        self.assertTrue(button.isEnabled())
        printer.busy = True
        printer.status_changed.emit()
        self.assertFalse(button.isEnabled())
        self.assertFalse(self.win.actions["print"].isEnabled())
        self.assertTrue(button.text().startswith("Sending"))
        printer.apply_status(PrinterStatus.parse(REAL_STATUS[:19] + b"\x01" + REAL_STATUS[20:]))  # phase: printing
        self.assertTrue(button.text().startswith("Printing"))
        self.assertEqual(printer.tone, "busy")
        printer.busy = False
        printer.apply_status(PrinterStatus.parse(REAL_STATUS))
        self.assertTrue(button.isEnabled())
        self.assertEqual(button.text(), "Print")

    def test_property_editor_and_panels(self):
        qr = self.insert("qrcode")
        self.win.properties._fields["size"].widget.setValue(7)
        self.assertEqual(qr.size, 7)
        self.win.label_panel.margin.setValue(4)
        self.assertEqual(self.doc.doc.margin_mm, 4)
        self.win.print_panel.flags["mirror"].setChecked(True)
        self.assertTrue(self.doc.doc.mirror)

    def test_drag_with_mouse_snaps_to_center(self):
        self.win.canvas.set_zoom(4)
        qr = self.insert("qrcode")
        self.doc.set_property(qr, "size", 6)
        self.doc.render_now()
        canvas = self.win.canvas
        box = self.doc.placed_of(qr).box
        top, bottom = self.doc.result.band
        start = canvas.to_screen(box).center().toPoint()
        off_center = (top + bottom) / 2 - (box[1] + box[3]) / 2 + 1  # 1 dot below the tape center
        end = start + QPoint(30, round(off_center * canvas.effective_zoom()))
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
        QTest.mouseMove(canvas, end)
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
        self.doc.render_now()
        top, bottom = self.doc.result.band
        box = self.doc.placed_of(qr).box
        self.assertAlmostEqual((box[1] + box[3]) / 2, (top + bottom) / 2, delta=1)
        self.assertTrue(self.doc.history.can_undo())

    def test_theme_switch_and_status(self):
        self.win.printer.apply_status(PrinterStatus.parse(REAL_STATUS))
        self.assertEqual(self.win.canvas.tape_rgb, (248, 214, 22))
        self.win.set_theme("dark")
        self.assertTrue(self.theme.dark)
        self.win.set_theme("light")
        self.assertFalse(self.theme.dark)

    def test_font_dropdown_previews_each_family(self):
        combo = self.win.format_bar.font_box
        self.assertIsInstance(combo.itemDelegate(), fontui.FontPreviewDelegate)
        index = combo.findText("Barlow Condensed")
        self.assertGreaterEqual(index, 0)
        self.assertEqual(fontui.PREVIEWS.qt_family("Barlow Condensed"), "Barlow Condensed")
        option = fontui.QStyleOptionViewItem()
        combo.itemDelegate().initStyleOption(option, combo.model().index(index, 0))
        self.assertEqual(option.font.family(), "Barlow Condensed")

    def test_symbol_fonts_hidden_unless_requested(self):
        combo = self.win.format_bar.font_box
        with mock.patch.object(fontui.PREVIEWS, "is_text_font", side_effect=lambda f: f != "Barlow Condensed"):
            fontui.FONT_LIST.refresh()
            self.assertEqual(combo.findText("Barlow Condensed"), -1)
            self.win.actions["all_fonts"].setChecked(True)
            self.assertGreaterEqual(combo.findText("Barlow Condensed"), 0)
            self.win.actions["all_fonts"].setChecked(False)
        fontui.FONT_LIST.refresh()
        self.assertGreaterEqual(combo.findText("Barlow Condensed"), 0)

    def test_web_font_dialog_lists_and_filters(self):
        fonts_ = [webfonts.WebFont("a", "Alpha Sans", "sans-serif", (400,), ("normal",), "OFL-1.1"),
                  webfonts.WebFont("b", "Beta Serif", "serif", (400,), ("normal",), "OFL-1.1")]
        with mock.patch.object(fontui.BackgroundRunner, "run"):  # no network
            dialog = fontui.WebFontDialog(self.win)
            self.addCleanup(dialog.deleteLater)
            dialog._on_list(fonts_, None)
            self.assertEqual(dialog.list.count(), 2)
            dialog.category.setCurrentIndex(dialog.category.findData("serif"))
            self.assertEqual([dialog.list.item(i).text() for i in range(dialog.list.count())], ["Beta Serif"])

    def test_close_saves_layout(self):
        self.doc.commit()
        self.doc._saved = self.doc.doc.to_json()  # nothing to ask on close
        with mock.patch("ptlabel.config.save") as save:
            self.win.close()
        cfg = save.call_args.args[0]
        self.assertTrue(cfg["window_state"])
        self.assertIn("snapping", cfg)


if __name__ == "__main__":
    unittest.main()
