import unittest

from ptlabel import barcodes
from ptlabel.model import BarcodeObject, LabelDocument, QRCodeObject
from ptlabel.render import print_pages, render


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


class QRCodeTest(unittest.TestCase):
    def test_high_resolution_keeps_modules_on_whole_pins(self):
        # at 360 dpi the rows are merged in pairs later; module rows must start on even rows of the band
        for size in (9.0, 8.67, 8.29):
            for rotation in (0, 90, 180, 270):
                doc = LabelDocument(tape_mm=12, high_res=True)
                doc.objects.append(QRCodeObject(x=2.13, y=1.17, size=size, rotation=rotation,
                                                data="https://example.com/inventar/server-01"))
                result = render(doc, dpi=360)
                top = result.band[0]
                ink = result.image.crop((0, top, result.image.width, result.band[1])).getbbox()
                self.assertEqual(ink[1] % 2, 0, (size, rotation))
                self.assertEqual((ink[3] - ink[1]) % 2, 0, (size, rotation))
                page = print_pages(doc)[0]
                histogram = page.histogram()
                self.assertEqual(sum(histogram) - histogram[0] - histogram[255], 0)  # pure black and white

    def test_dense_code_warns(self):
        doc = LabelDocument(tape_mm=6)
        doc.objects.append(QRCodeObject(size=4.5, data="https://intranet.example.org/" + "x" * 120))
        self.assertTrue(any("QR code" in w for w in render(doc).warnings))
        doc = LabelDocument(tape_mm=12)
        doc.objects.append(QRCodeObject(y=doc.tape.band_top_mm, size=9.9, data="PT-Label"))
        self.assertEqual(render(doc).warnings, [])


if __name__ == "__main__":
    unittest.main()
