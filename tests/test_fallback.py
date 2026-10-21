import unittest

from ptlabel import fallback, fonts
from ptlabel.model import LabelDocument, TextObject
from ptlabel.render import render

NOWHERE = "\U000F0001"  # private use: no font has it


class FallbackTest(unittest.TestCase):
    def setUp(self):
        fonts.REGISTRY.ensure_loaded()

    def test_glyph_detection(self):
        face = fonts.REGISTRY.resolve("Barlow Condensed", False, False)
        self.assertEqual(face.family, "Barlow Condensed")
        self.assertTrue(fallback.has_glyph(face, "A"))
        self.assertTrue(fallback.has_glyph(face, " "))
        self.assertFalse(fallback.has_glyph(face, "→"))  # not in the latin subset

    def test_missing_characters_come_from_another_font(self):
        if fallback.FINDER.family_for("→") is None:
            self.skipTest("no installed font has an arrow")
        runs = fallback.runs("A → B", "Barlow Condensed", 40)
        self.assertEqual([chunk for _, _, chunk in runs], ["A ", "→", " B"])
        self.assertNotEqual(runs[1][0].getname()[0], "Barlow Condensed")
        self.assertEqual(runs[0][0].getname()[0], "Barlow Condensed")

    def test_text_wider_with_fallback_and_warning_for_unknown_characters(self):
        doc = LabelDocument()
        doc.objects.append(TextObject(text=f"A{NOWHERE}", font="Barlow Condensed"))
        result = render(doc)
        self.assertTrue(any(NOWHERE in w for w in result.warnings))
        self.assertEqual(fallback.missing("Ä€", "Barlow Condensed"), [])

    def test_cache_follows_font_changes(self):
        fallback.FINDER.family_for("A")
        fonts.REGISTRY.reload()  # e.g. fonts were added: the next lookup starts afresh
        fallback.FINDER.family_for("B")
        self.assertNotIn("A", fallback.FINDER._families)
        self.assertIn("B", fallback.FINDER._families)


if __name__ == "__main__":
    unittest.main()
