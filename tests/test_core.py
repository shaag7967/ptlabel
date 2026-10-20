import os
import random
import unittest
from datetime import datetime
from unittest import mock

from PIL import Image

from ptlabel.model import (BarcodeObject, FrameObject, LabelDocument, LineObject, QRCodeObject, TextObject,
                           expand)
from ptlabel.printer import NetworkPrinter, PrinterStatus
from ptlabel.raster import PrintOptions, band_to_lines, build_job, packbits, unpackbits
from ptlabel.render import print_pages, render
from ptlabel.tapes import TAPES, tape_for_width

# status block read via SNMP from the real PT-P750W (12 mm yellow/black laminated tape)
REAL_STATUS = bytes.fromhex("80 20 42 30 68 30 04 00 00 00 0c 01 00 00 00 00"
                            "00 00 00 00 00 00 00 00 06 08 00 00 00 00 00 00")


def parse_job(job: bytes):
    """Split a job into (command, payload) tuples."""
    assert job[:100] == b"\x00" * 100
    i, out = 100, []
    while i < len(job):
        c = job[i]
        if job[i:i + 2] == b"\x1b@":
            out.append(("init", b"")); i += 2
        elif job[i:i + 3] == b"\x1bia":
            out.append(("mode", job[i + 3:i + 4])); i += 4
        elif job[i:i + 3] == b"\x1biz":
            out.append(("info", job[i + 3:i + 13])); i += 13
        elif job[i:i + 3] in (b"\x1biM", b"\x1biA", b"\x1biK"):
            out.append((job[i + 2:i + 3].decode(), job[i + 3:i + 4])); i += 4
        elif job[i:i + 3] == b"\x1bid":
            out.append(("margin", job[i + 3:i + 5])); i += 5
        elif c == ord("M"):
            out.append(("compression", job[i + 1:i + 2])); i += 2
        elif c == ord("G"):
            n = int.from_bytes(job[i + 1:i + 3], "little")
            out.append(("line", unpackbits(job[i + 3:i + 3 + n]))); i += 3 + n
        elif c == ord("Z"):
            out.append(("line", bytes(16))); i += 1
        elif c in (0x0C, 0x1A):
            out.append(("print", bytes([c]))); i += 1
        else:
            raise AssertionError(f"unknown command at {i}: {job[i:i + 4].hex()}")
    return out


class PackBitsTest(unittest.TestCase):
    def test_roundtrip(self):
        rnd = random.Random(1)
        samples = [b"", b"\x00", bytes(16), b"\xff" * 16, b"\x01\x02\x03", b"\x00\x00\x01\x01\x01\x02",
                   bytes(300), os.urandom(400)]
        samples += [bytes(rnd.choice((0, 0, 255, 7)) for _ in range(rnd.randint(1, 40))) for _ in range(300)]
        for data in samples:
            self.assertEqual(unpackbits(packbits(data)), data)

    def test_runs_are_compressed(self):
        self.assertEqual(packbits(bytes(16)), b"\xf1\x00")


class RasterTest(unittest.TestCase):
    def test_bit_placement(self):
        tape = tape_for_width(12)  # 29 margin pins
        band = Image.new("L", (3, tape.print_pins), 0)
        band.putpixel((0, 0), 255)  # top row, first column
        band.putpixel((2, tape.print_pins - 1), 255)  # bottom row, last column
        lines = band_to_lines(band, tape)
        self.assertEqual(len(lines), 3)
        self.assertTrue(all(len(line) == 16 for line in lines))
        top_pin = tape.margin_pins
        bottom_pin = tape.margin_pins + tape.print_pins - 1
        self.assertEqual(lines[0], self._line_with(top_pin))
        self.assertEqual(lines[1], bytes(16))
        self.assertEqual(lines[2], self._line_with(bottom_pin))

    @staticmethod
    def _line_with(pin):
        line = bytearray(16)
        line[pin // 8] |= 0x80 >> (pin % 8)
        return bytes(line)

    def test_margin_units(self):
        self.assertEqual(PrintOptions(margin_mm=10).margin_dots(), 71)
        self.assertEqual(PrintOptions(margin_mm=10, high_res=True).margin_dots(), 142)  # measured: 10 mm

    def test_job_structure(self):
        tape = tape_for_width(24)
        page = Image.new("L", (40, tape.print_pins), 0)
        page.paste(255, (5, 5, 30, 60))
        opts = PrintOptions(auto_cut=True, half_cut=True, chain=False, margin_mm=2)
        cmds = parse_job(build_job([page, page], tape, opts))
        kinds = [c for c, _ in cmds if c != "line"]
        self.assertEqual(kinds[:2], ["init", "mode"])
        infos = [p for c, p in cmds if c == "info"]
        self.assertEqual(len(infos), 2)
        self.assertEqual(infos[0][2], 24)  # width
        self.assertEqual(int.from_bytes(infos[0][4:8], "little"), 40)  # raster lines
        self.assertEqual((infos[0][8], infos[1][8]), (0, 1))  # first page / following page
        self.assertEqual([p for c, p in cmds if c == "M"][0], b"\x40")
        self.assertEqual([p for c, p in cmds if c == "K"][0], b"\x0c")
        self.assertEqual([p for c, p in cmds if c == "margin"][0], (14).to_bytes(2, "little"))
        self.assertEqual([p for c, p in cmds if c == "print"], [b"\x0c", b"\x1a"])
        self.assertEqual(sum(1 for c, _ in cmds if c == "line"), 80)


class StatusTest(unittest.TestCase):
    def test_real_status(self):
        st = PrinterStatus.parse(REAL_STATUS)
        self.assertEqual(st.model, "PT-P750W")
        self.assertEqual(st.errors, [])
        self.assertEqual(st.tape.width_mm, 12)
        self.assertIn("Gelb / Schwarz", st.describe_media())
        self.assertIn("laminiert", st.describe_media())

    def test_errors(self):
        raw = bytearray(REAL_STATUS)
        raw[8], raw[9] = 0x01, 0x10
        self.assertEqual(PrinterStatus.parse(bytes(raw)).errors, ["Kein Band eingelegt", "Abdeckung offen"])

    def test_transient_error_is_ignored(self):
        flicker = bytearray(REAL_STATUS)
        flicker[9], flicker[18] = 0x04, 0x02  # short "communication error" seen on the real printer
        cover_open = bytearray(REAL_STATUS)
        cover_open[9] = 0x10
        cases = [
            ([flicker, REAL_STATUS], []),
            ([cover_open, cover_open, cover_open], ["Abdeckung offen"]),
        ]
        for reads, expected in cases:
            printer = NetworkPrinter("test")
            queue = [PrinterStatus.parse(bytes(r)) for r in reads]
            printer._read_status = lambda: queue.pop(0)
            with mock.patch("ptlabel.printer.time.sleep"):
                self.assertEqual(printer.status().errors, expected)
            self.assertEqual(queue, [])


class RenderTest(unittest.TestCase):
    def test_auto_text_fits_band(self):
        for tape in TAPES:
            doc = LabelDocument(tape_mm=tape.width_mm, objects=[TextObject(text="Hallo Welt\nZeile 2")])
            res = render(doc)
            top, bottom = res.band
            self.assertEqual(bottom - top, tape.print_pins)
            box = res.placed[0].box
            self.assertGreaterEqual(box[1], top, tape)
            self.assertLessEqual(box[3], bottom, tape)
            self.assertGreater(box[3] - box[1], 0.8 * tape.print_pins, tape)  # fills the band
            self.assertEqual(res.warnings, [])

    def test_all_objects_and_print_pages(self):
        doc = LabelDocument(tape_mm=24, copies=3, objects=[
            TextObject(text="Nr. {nr:03}"),
            QRCodeObject(x=30, y=3, data="https://example.com", size=17),
            BarcodeObject(x=50, y=3, data="400638133393", symbology="ean13", height=10),
            BarcodeObject(x=90, y=3, data="ABC-123", symbology="code128", height=10),
            FrameObject(x=2.5, y=3, width=150, height=18),
            LineObject(x=5, y=12, length=10),
        ])
        res = render(doc)
        self.assertEqual(res.warnings, [])
        pages = print_pages(doc)
        self.assertEqual(len(pages), 3)
        self.assertNotEqual(pages[0].tobytes(), pages[1].tobytes())  # numbering differs
        for page in pages:
            self.assertEqual(page.height, 128)
            self.assertEqual(page.width, res.image.width - 2 * res.margin_px)
        doc.high_res = True
        hi = print_pages(doc)[0]
        self.assertEqual(hi.height, 128)
        self.assertAlmostEqual(hi.width / pages[0].width, 2, delta=0.05)

    def test_invalid_barcode_warns(self):
        doc = LabelDocument(objects=[BarcodeObject(data="abc", symbology="ean13")])
        self.assertTrue(render(doc).warnings)

    def test_placeholders(self):
        now = datetime(2026, 10, 20, 14, 5)
        self.assertEqual(expand("{nr:03}/{datum}/{zeit}", 7, now), "007/20.10.2026/14:05")
        self.assertEqual(expand("{datum:%y}", 1, now), "26")
        self.assertEqual(expand("{unbekannt} {nr}", 1, now), "{unbekannt} {nr}")
        self.assertEqual(expand("{nr.__class__}", 1, now), "{nr.__class__}")


class DocumentTest(unittest.TestCase):
    def test_json_roundtrip(self):
        doc = LabelDocument(tape_mm=18, copies=2, objects=[TextObject(text="Ä"), QRCodeObject(), LineObject()])
        again = LabelDocument.from_json(doc.to_json())
        self.assertEqual(again, doc)


if __name__ == "__main__":
    unittest.main()
