"""Series printing from a table: every row of a CSV file fills the {column} placeholders once."""

from __future__ import annotations

import csv
import io
import re
import string
from dataclasses import dataclass
from pathlib import Path

from .i18n import tr
from .model import LabelDocument

BUILTIN_FIELDS = {"nr", "date", "time", "datum", "zeit"}
_UNSAFE = re.compile(r"[.\[\]{}:!]")  # characters with a meaning inside {placeholders}


@dataclass
class DataTable:
    path: str
    columns: list[str]
    rows: list[dict[str, str]]

    def __len__(self) -> int:
        return len(self.rows)

    def select(self, indices: list[int] | None) -> list[dict[str, str]]:
        """Rows by 0-based index, all rows for None."""
        return list(self.rows) if indices is None else [self.rows[i] for i in indices]


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):  # Excel on Windows saves CSV in cp1252
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def _column_names(header: list[str]) -> list[str]:
    names = []
    for i, name in enumerate(header):
        name = _UNSAFE.sub("_", name.strip()) or f"column{i + 1}"
        base, n = name, 2
        while name in names:
            name, n = f"{base}_{n}", n + 1
        names.append(name)
    return names


def read_csv(path: str | Path) -> DataTable:
    """Read a CSV file with a header row; the separator (; , tab |) is detected."""
    text = _decode(Path(path).read_bytes())
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=";,\t|")
    except csv.Error:  # e.g. a single column: guess from the header line
        header = text.split("\n", 1)[0]

        class dialect(csv.excel):
            delimiter = ";" if header.count(";") > header.count(",") else ","
    lines = [row for row in csv.reader(io.StringIO(text), dialect) if any(cell.strip() for cell in row)]
    if not lines:
        raise ValueError(tr("The file contains no data"))
    columns = _column_names(lines[0])
    rows = [{name: (row[i].strip() if i < len(row) else "") for i, name in enumerate(columns)}
            for row in lines[1:]]
    return DataTable(str(path), columns, rows)


def parse_rows(spec: str, count: int) -> list[int]:
    """'1-5, 8' -> [0, 1, 2, 3, 4, 7] (1-based input, 0-based output); empty = all rows."""
    spec = spec.strip()
    if not spec:
        return list(range(count))
    indices = []
    for part in spec.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        first, dash, last = part.partition("-")
        try:
            start = int(first)
            end = int(last) if last.strip() else (count if dash else start)  # "3-" = up to the end
        except ValueError as exc:
            raise ValueError(tr("Invalid row selection: {rows}").format(rows=spec)) from exc
        if not 1 <= start <= end <= count:
            raise ValueError(tr("Rows must be between 1 and {count}: {rows}").format(count=count, rows=part))
        indices += [i for i in range(start - 1, end) if i not in indices]
    return indices


def used_fields(doc: LabelDocument) -> set[str]:
    """Names of all {placeholders} in the texts, QR codes and barcodes of ``doc``."""
    names = set()
    for obj in doc.objects:
        for attr in ("text", "data"):
            value = getattr(obj, attr, None)
            if not isinstance(value, str) or "{" not in value:
                continue
            try:
                names |= {name for _, name, _, _ in string.Formatter().parse(value) if name}
            except ValueError:
                pass
    return names


def missing_columns(doc: LabelDocument, table: DataTable) -> list[str]:
    """Placeholders of ``doc`` that are neither built in nor a column of ``table``."""
    return sorted(used_fields(doc) - BUILTIN_FIELDS - set(table.columns))
