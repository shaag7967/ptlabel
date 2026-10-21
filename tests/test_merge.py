import tempfile
import unittest
from pathlib import Path

from ptlabel import cli, merge
from ptlabel.model import LabelDocument, TextObject, expand
from ptlabel.render import print_pages


class MergeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, text: str, encoding="utf-8") -> Path:
        path = Path(self.tmp.name) / "data.csv"
        path.write_text(text, encoding=encoding)
        return path

    def test_reads_excel_csv_with_semicolons_and_cp1252(self):
        table = merge.read_csv(self.write("Kabel;Größe\nK-001;Ø 6\n\nK-002;Ø 8\n", "cp1252"))
        self.assertEqual(table.columns, ["Kabel", "Größe"])
        self.assertEqual(table.rows, [{"Kabel": "K-001", "Größe": "Ø 6"}, {"Kabel": "K-002", "Größe": "Ø 8"}])

    def test_comma_tab_and_odd_headers(self):
        self.assertEqual(merge.read_csv(self.write("a,b\n1,2\n")).columns, ["a", "b"])
        self.assertEqual(merge.read_csv(self.write("a\tb\n1\t2\n")).rows, [{"a": "1", "b": "2"}])
        table = merge.read_csv(self.write("Port.Nr;;Port.Nr\n1;2;3\n"))
        self.assertEqual(table.columns, ["Port_Nr", "column2", "Port_Nr_2"])
        with self.assertRaises(ValueError):
            merge.read_csv(self.write("\n\n"))

    def test_row_selection(self):
        self.assertEqual(merge.parse_rows("", 4), [0, 1, 2, 3])
        self.assertEqual(merge.parse_rows("1-2, 4", 4), [0, 1, 3])
        self.assertEqual(merge.parse_rows("3-", 4), [2, 3])
        for bad in ("0", "5", "x", "3-2"):
            with self.assertRaises(ValueError):
                merge.parse_rows(bad, 4)

    def test_placeholders_and_missing_columns(self):
        doc = LabelDocument()
        doc.objects.append(TextObject(text="{Kabel} → {Ziel} #{nr:03} {datum}"))
        table = merge.DataTable("x", ["Kabel"], [])
        self.assertEqual(merge.used_fields(doc), {"Kabel", "Ziel", "nr", "datum"})
        self.assertEqual(merge.missing_columns(doc, table), ["Ziel"])
        self.assertEqual(expand("{Kabel}/{nr}", 7, fields={"Kabel": "K-1"}), "K-1/7")

    def test_one_label_per_record_and_copy_counting_on(self):
        doc = LabelDocument(copies=2, counter_start=5)
        doc.objects.append(TextObject(text="{Kabel} {nr}"))
        pages = print_pages(doc, records=[{"Kabel": "A"}, {"Kabel": "B"}])
        self.assertEqual(len(pages), 4)

    def test_cli_series(self):
        path = self.write("Kabel\nK-001\nK-002\nK-003\n")
        out = Path(self.tmp.name) / "job.bin"
        self.assertEqual(cli.main(["text", "{Kabel}", "--tape", "12", "--csv", str(path), "--rows", "2-3",
                                   "--output", str(out)]), 0)
        self.assertGreater(out.stat().st_size, 100)
        self.assertEqual(cli.main(["text", "{Typ}", "--tape", "12", "--csv", str(path), "--output", str(out)]), 1)


if __name__ == "__main__":
    unittest.main()
