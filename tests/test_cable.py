import math
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from ptlabel import cli
from ptlabel.model import CABLE_FLAG, LabelDocument, QRCodeObject, TextObject
from ptlabel.render import print_pages, render


def flag(**kwargs) -> LabelDocument:
    doc = LabelDocument(tape_mm=12, layout=CABLE_FLAG, **kwargs)
    doc.objects.append(TextObject(text="SW01-P12", h_align="center", align="center"))
    return doc


class CableFlagTest(unittest.TestCase):
    def test_strip_is_flag_wrap_flag(self):
        doc = flag(cable_diameter_mm=6)
        result = render(doc)
        x0, x1 = result.face_box
        w0, w1 = result.wrap
        self.assertEqual((x0, x1), (0, w0))
        self.assertAlmostEqual((w1 - w0) / result.scale, math.pi * 6 + 1, delta=0.2)
        self.assertEqual(result.image.width, 2 * x1 + (w1 - w0))
        first = result.image.crop((0, 0, x1, result.image.height))
        second = result.image.crop((w1, 0, w1 + x1, result.image.height))
        self.assertEqual(first.tobytes(), second.tobytes())  # both flags read the same
        self.assertEqual(result.warnings, [])

    def test_wrap_area_is_blank_apart_from_fold_marks(self):
        result = render(flag(fold_marks=False))
        w0, w1 = result.wrap
        self.assertIsNone(result.image.crop((w0, 0, w1, result.image.height)).getbbox())
        marked = render(flag(fold_marks=True))
        bbox = marked.image.crop((w0, 0, w1, marked.image.height)).getbbox()
        self.assertEqual((bbox[0], bbox[2]), (0, w1 - w0))  # only at both folds

    def test_fixed_flag_length_and_centered_text(self):
        result = render(flag(auto_length=False, length_mm=30))
        self.assertAlmostEqual(result.face_mm, 30, delta=0.2)
        x0, _, x1, _ = result.placed[0].box
        self.assertAlmostEqual((x0 + x1) / 2, result.face_box[1] / 2, delta=1)

    def test_print_pages_and_high_resolution(self):
        doc = flag(copies=2)
        pages = print_pages(doc)
        self.assertEqual(len(pages), 2)
        result = render(doc)
        self.assertEqual(pages[0].width, result.image.width - 2 * result.margin_px)
        doc.high_res = True
        self.assertEqual(print_pages(doc)[0].height, doc.tape.print_pins)

    def test_old_files_stay_normal_labels(self):
        doc = LabelDocument.from_dict({"format": "ptlabel", "version": 1, "tape_mm": 12, "objects": []})
        self.assertFalse(doc.is_cable_flag)
        saved = LabelDocument.from_json(flag(cable_diameter_mm=8).to_json())
        self.assertTrue(saved.is_cable_flag)
        self.assertEqual(saved.cable_diameter_mm, 8)

    def test_cli_cable_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            preview = Path(tmp) / "flag.png"
            self.assertEqual(cli.main(["cable", "SW01-P12", "--tape", "12", "--diameter", "8",
                                       "--preview", str(preview)]), 0)
            with Image.open(preview) as img:
                width = img.width
        doc = flag(cable_diameter_mm=8)
        self.assertEqual(width, render(doc).image.width)

    def test_qr_code_on_flag(self):
        doc = flag()
        doc.objects.insert(0, QRCodeObject(x=2, y=doc.tape.band_top_mm, size=9.9, data="SW01-P12"))
        doc.objects[1].h_align = "free"
        doc.objects[1].x = 13.5
        result = render(doc)
        self.assertEqual(result.warnings, [])
        self.assertEqual(len(result.placed), 2)


if __name__ == "__main__":
    unittest.main()
