import gettext
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageFont

from ptlabel import fonts, i18n, webfonts

FIELD = re.compile(r"\{(\w*)")


class TranslationTest(unittest.TestCase):
    def test_german_catalog_is_complete_and_keeps_placeholders(self):
        de = i18n.translation(["de"])
        self.assertIsInstance(de, gettext.GNUTranslations)
        catalog = {k: v for k, v in de._catalog.items() if k}  # skip the header entry
        self.assertGreater(len(catalog), 200)
        aliases = {"datum": "date", "zeit": "time"}  # German placeholder names in the help text
        names = lambda text: sorted(aliases.get(n, n) for n in FIELD.findall(text))  # noqa: E731
        for key, translated in catalog.items():
            msgid = key[0] if isinstance(key, tuple) else key
            self.assertTrue(translated, msgid)
            self.assertEqual(names(msgid), names(translated), msgid)

    def test_english_fallback(self):
        self.assertEqual(i18n.translation(["fr"]).gettext("Cover open"), "Cover open")
        self.assertEqual(i18n.translation(["de_DE.UTF-8"]).gettext("Cover open"), "Abdeckung offen")


class FontTest(unittest.TestCase):
    def test_bundled_fonts_are_found(self):
        fonts.REGISTRY.reload()
        for family in ("Atkinson Hyperlegible", "Barlow Condensed", "JetBrains Mono"):
            self.assertEqual(fonts.REGISTRY.find_family(family.lower()), family)
            self.assertTrue(fonts.REGISTRY.resolve(family, True, True).is_bold)

    def test_fonts_without_latin_glyphs_are_hidden(self):
        class BoxFont:  # draws the same placeholder box for every character
            def getmask(self, _char):
                return Image.new("L", (5, 8), 255).im
        self.assertFalse(fonts._draws_latin(BoxFont()))
        bundled = next((fonts.BUNDLED_FONT_DIR / "jetbrains-mono").glob("*400-normal.ttf"))
        self.assertTrue(fonts._draws_latin(ImageFont.truetype(str(bundled), 32)))
        registry = fonts.FontRegistry()
        registry._families = {"Latin": [fonts.Face("a", 0, "Latin", "Regular")],
                              "Hebrew": [fonts.Face("b", 0, "Hebrew", "Regular", latin=False)]}
        registry._lookup = {"latin": "Latin", "hebrew": "Hebrew"}
        registry._loaded = True
        self.assertEqual(registry.families(), ["Latin"])
        self.assertEqual(registry.families(include_all=True), ["Hebrew", "Latin"])
        self.assertEqual(registry.find_family("hebrew"), "Hebrew")  # documents may still use it

    def test_install_font_files(self):
        source = next((fonts.BUNDLED_FONT_DIR / "barlow-condensed").glob("*400-normal.ttf"))
        with tempfile.TemporaryDirectory() as tmp:
            junk = Path(tmp) / "readme.ttf"
            junk.write_text("not a font")
            target = Path(tmp) / "fonts"
            families = fonts.install_font_files([source, junk], target)
            self.assertEqual(families, ["Barlow Condensed"])
            self.assertEqual([p.name for p in target.iterdir()], [source.name])


class WebFontTest(unittest.TestCase):
    LIST = [{"id": "barlow-condensed", "family": "Barlow Condensed", "subsets": ["latin"], "weights": [300, 700],
             "styles": ["normal"], "category": "sans-serif", "license": "OFL-1.1"},
            {"id": "noto-sans-jp", "family": "Noto Sans JP", "subsets": ["japanese"], "weights": [400],
             "styles": ["normal"], "category": "sans-serif", "license": "OFL-1.1"}]

    def fake_get(self, url):
        if url.endswith("type=google&subsets=latin"):
            return json.dumps(self.LIST).encode()
        if url.endswith("/barlow-condensed"):
            variant = lambda w: {"normal": {"latin": {"url": {"ttf": f"https://cdn/{w}.ttf"}}}}  # noqa: E731
            return json.dumps({"variants": {"300": variant(300), "700": variant(700)}}).encode()
        weight = url.rsplit("/", 1)[1].split(".")[0]
        name = "400-normal" if weight == "300" else "700-normal"
        return next((fonts.BUNDLED_FONT_DIR / "barlow-condensed").glob(f"*{name}.ttf")).read_bytes()

    def test_list_and_install(self):
        with mock.patch.object(webfonts, "_get", side_effect=self.fake_get) as get:
            listed = webfonts.list_fonts(refresh=True)
            self.assertEqual([f.family for f in listed], ["Barlow Condensed"])
            families = webfonts.install(listed[0])
        self.assertEqual(families, ["Barlow Condensed"])
        folder = fonts.user_font_dir() / "barlow-condensed"
        self.assertEqual(sorted(p.name for p in folder.iterdir()),
                         ["barlow-condensed-300-normal.ttf", "barlow-condensed-700-normal.ttf"])
        self.assertIn("https://cdn/300.ttf", [c.args[0] for c in get.call_args_list])
        shutil.rmtree(folder)
        fonts.REGISTRY.reload()


if __name__ == "__main__":
    unittest.main()
