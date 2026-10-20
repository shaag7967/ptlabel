import tempfile
import unittest
from unittest import mock

try:
    from PySide6.QtWidgets import QApplication
except ImportError:  # pragma: no cover
    QApplication = None

if QApplication is not None:
    from ptlabel import webfonts
    from ptlabel.gui import fontui, window
    from ptlabel.gui.qtutil import PAD
    from ptlabel.model import LabelDocument, TextObject
    from ptlabel.printer import PrinterStatus

# status block of a PT-P750W with 12 mm yellow/black tape (see test_core.py)
REAL_STATUS = bytes.fromhex("80 20 42 30 68 30 04 00 00 00 0c 01 00 00 00 00"
                            "00 00 00 00 00 00 00 00 06 08 00 00 00 00 00 00")


@unittest.skipIf(QApplication is None, "PySide6 not installed")
class MainWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        patcher = mock.patch.object(window, "discover_printers", return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.win = window.MainWindow()
        self.addCleanup(self.win.deleteLater)
        self.win._render_now()

    def test_insert_undo_redo(self):
        win = self.win
        for kind in ("text", "qrcode", "barcode", "frame", "line"):
            win.insert(kind)
            win._render_now()
        self.assertEqual(len(win.doc.objects), 6)
        win.undo()
        self.assertEqual(len(win.doc.objects), 5)
        win.redo()
        self.assertEqual(len(win.doc.objects), 6)

    def test_nudge_updates_object_and_field(self):
        win = self.win
        win.insert("qrcode")
        obj = win.selected
        x, y = obj.x, obj.y
        win.nudge(0.5, -0.1)
        self.assertAlmostEqual(obj.x, x + 0.5)
        self.assertAlmostEqual(obj.y, y - 0.1)
        self.assertAlmostEqual(win._fields["x"].value(), obj.x)

    def test_editing_size_freezes_auto_text(self):
        win = self.win
        text = win.doc.objects[0]
        self.assertIsInstance(text, TextObject)
        self.assertTrue(text.auto_size)
        win._fields["size"].widget.setValue(10)
        self.assertFalse(text.auto_size)
        self.assertEqual(text.size, 10)

    def test_canvas_size_follows_render(self):
        win = self.win
        res, z = win.result, win.current_zoom()
        self.assertEqual(win.canvas.minimumWidth(), 2 * PAD + res.image.width * z)

    def test_drag_moves_object(self):
        win = self.win
        win.insert("qrcode")
        win._render_now()
        obj = win.selected
        placed = win._placed_of(obj)
        cx, cy = (placed.box[0] + placed.box[2]) / 2, (placed.box[1] + placed.box[3]) / 2
        x0 = obj.x
        win.on_press(cx, cy)
        win.on_motion(cx + 10 * win.result.scale, cy)
        win.on_release()
        self.assertAlmostEqual(obj.x, x0 + 10, places=1)

    def test_status_colors_and_save(self):
        win = self.win
        win._apply_status(PrinterStatus.parse(REAL_STATUS))
        self.assertEqual(win._preview_colors()[0], (248, 214, 22))
        with tempfile.TemporaryDirectory() as tmp:
            win.path = window.Path(tmp) / "t.ptlabel"
            self.assertTrue(win.save_document())
            self.assertEqual(LabelDocument.load(win.path).to_json(), win.doc.to_json())
            self.assertFalse(win._is_modified())

    def test_font_dropdown_previews_each_family(self):
        win = self.win
        win.select(win.doc.objects[0])
        combo = win._fields["font"].widget
        self.assertIsInstance(combo.itemDelegate(), fontui.FontPreviewDelegate)
        index = combo.findText("Barlow Condensed")
        self.assertGreaterEqual(index, 0)
        self.assertEqual(fontui.PREVIEWS.qt_family("Barlow Condensed"), "Barlow Condensed")
        option = fontui.QStyleOptionViewItem()
        combo.itemDelegate().initStyleOption(option, combo.model().index(index, 0))
        self.assertEqual(option.font.family(), "Barlow Condensed")

    def test_web_font_dialog_lists_and_filters(self):
        fonts_ = [webfonts.WebFont("a", "Alpha Sans", "sans-serif", (400,), ("normal",), "OFL-1.1"),
                  webfonts.WebFont("b", "Beta Serif", "serif", (400,), ("normal",), "OFL-1.1")]
        with mock.patch.object(fontui.BackgroundRunner, "run"):  # no network
            dialog = fontui.WebFontDialog(self.win)
        self.addCleanup(dialog.deleteLater)
        with mock.patch.object(fontui.BackgroundRunner, "run"):
            dialog._on_list(fonts_, None)
            self.assertEqual(dialog.list.count(), 2)
            dialog.category.setCurrentIndex(dialog.category.findData("serif"))
            self.assertEqual([dialog.list.item(i).text() for i in range(dialog.list.count())], ["Beta Serif"])


if __name__ == "__main__":
    unittest.main()
