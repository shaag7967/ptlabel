import unittest

from ptlabel import barcodes
from ptlabel.model import BarcodeObject, LabelDocument
from ptlabel.render import render


class BarcodeTest(unittest.TestCase):
    def test_all_samples_encode(self):
        for symbology, data in barcodes.SAMPLES.items():
            code = barcodes.encode(symbology, data)
            self.assertTrue(set(code.modules) <= {"0", "1"}, symbology)

    def test_code39_without_checksum(self):
        self.assertEqual(barcodes.encode("code39", "ABC-123").text, "ABC-123")

    def test_ean13_layout(self):
        code = barcodes.encode("ean13", "400638133393")
        self.assertEqual(code.text, "4006381333931")
        self.assertEqual([g.text for g in code.groups], ["4", "006381", "333931"])
        self.assertEqual(code.guards, [(0, 3), (45, 50), (92, 95)])
        for start, end in code.guards:  # guard patterns: 101, 01010, 101
            self.assertIn(code.modules[start:end], ("101", "01010"))

    def test_invalid_data_explains_the_rule(self):
        with self.assertRaises(ValueError) as cm:
            barcodes.encode("ean13", "12345678")
        self.assertIn("12 digits", str(cm.exception))
        self.assertFalse(barcodes.is_valid("ean8", "ABC"))

    def test_guard_bars_are_longer(self):
        doc = LabelDocument(tape_mm=24)
        doc.objects.append(BarcodeObject(x=2, y=4, symbology="ean13", data="400638133393", height=14))
        result = render(doc)
        self.assertEqual(result.warnings, [])
        img = result.image
        x0, y0, x1, y1 = result.placed[0].box
        column_heights = [sum(1 for y in range(y0, y1) if img.getpixel((x, y))) for x in range(x0, x1)]
        bars = sorted(set(h for h in column_heights if h))
        self.assertGreater(bars[-1], bars[0])  # guards reach into the text line


if __name__ == "__main__":
    unittest.main()
