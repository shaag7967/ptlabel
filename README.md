# PT-Label – label editor for the Brother PT-P750W

[![CI](https://github.com/shaag7967/ptlabel/actions/workflows/ci.yml/badge.svg)](https://github.com/shaag7967/ptlabel/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/shaag7967/ptlabel/blob/main/LICENSE)

Design and print labels on a Brother PT-P750W over Wi-Fi. Runs on Windows and Linux and needs
neither P-touch Editor nor the Brother driver. The user interface is available in English and German.

![PT-Label main window](https://raw.githubusercontent.com/shaag7967/ptlabel/main/docs/screenshots/main.png)

## Features

- WYSIWYG editor that previews the colors of the loaded tape; non-printable areas are shaded gray.
- Objects: text (multi-line, font, bold/italic/underline, inverted, alignment, automatic size),
  QR code, barcode (Code 128, Code 39, EAN-13, EAN-8, UPC-A, ITF, Codabar), image (PNG/JPG/…,
  threshold or dithering), frame, line. Objects can be rotated in 90° steps.
- Move objects with the mouse or the arrow keys, resize them with the handle at the bottom right,
  undo/redo. While dragging, objects snap to the tape center, the margins and other objects.
- Modern Qt interface with icons, light and dark theme, dockable panels (properties, label, print,
  object list) and a format toolbar for texts; the panel layout is remembered.
- Tape widths 3.5 / 6 / 9 / 12 / 18 / 24 mm, automatic or fixed label length, margins.
- Print options: copies, automatic cut, half cut, chain printing, mirror, high resolution.
- Placeholders for serial numbers and dates: `{nr}`, `{nr:03}`, `{date}`, `{time}`.
- Cable labels: cable flags (same text on both sides of the cable) and cable wraps (text repeated
  around the cable).
- Series printing from CSV tables: every row fills the `{column}` placeholders of one label.
- The printer status (tape, colors, errors such as “cover open”) is queried continuously.
- Printers on the network are found automatically.
- Fonts: all system fonts plus three bundled ones; more can be added from files or downloaded from
  Google Fonts. The font list shows every font in its own typeface.
- Labels are saved as `.ptlabel` files (JSON, images embedded) and can be exported as PNG.
- Command line interface for quick labels and scripts.

## Installation

Python 3.10 or newer is required, on Windows and Linux alike. Install PT-Label straight from GitHub
with [pipx](https://pipx.pypa.io) (or `pip`):

```sh
pipx install git+https://github.com/shaag7967/ptlabel.git
ptlabel                     # starts the user interface
```

Later updates: `pipx upgrade ptlabel`.

On Windows, `ptlabel-gui` starts the user interface without a console window.

The user interface uses Qt (PySide6), which is installed automatically. Some Linux distributions
additionally need the `libxcb-cursor0` library (Debian/Ubuntu: `sudo apt install libxcb-cursor0`).

### Language

The language follows the system settings. To choose it explicitly, set the environment variable
`LANGUAGE` (e.g. `LANGUAGE=en ptlabel`) or add `"language": "de"` to the settings file
(`~/.config/ptlabel/config.json` on Linux, `%APPDATA%\ptlabel\config.json` on Windows).

### Printer setup

The printer must be switched on and connected to the network. On first start PT-Label searches for
it. Otherwise enter its host name (`BRW…` followed by its MAC address, printed on the network
configuration report) or its IP address under “Print → Printer”. The PT-P750W switches itself off
after a while without use; the status line then reports that it does not respond until it is
switched on again.

## Usage

The window consists of the label preview in the middle, two toolbars and the panels
**Objects** (all objects; drag entries to change which one is in front) and **Properties** (settings
of the selected object) on the left, **Label** (label type, tape, length, margins) and **Print**
(printer, copies, cutting) on the right, and **Data** (series printing, shown when a CSV file is
loaded) below the preview. Panels can be moved, stacked as tabs, detached or closed; “View → Panels
and toolbars” brings them back and resets the layout. “View → Theme” switches between system, light
and dark:

![Dark theme](https://raw.githubusercontent.com/shaag7967/ptlabel/main/docs/screenshots/dark.png)

| Action | How |
|---|---|
| Insert an object | toolbar “Text”, “QR code” … or the “Insert” menu |
| Move | drag with the mouse, arrow keys 0.5 mm, Shift+arrow 0.1 mm |
| Align | objects snap to tape center, margins and other objects (magenta guides); Alt moves freely, the magnet button switches snapping off |
| Resize | drag the white square at the bottom right of the selected object |
| Edit text | double-click the object, the “Text” field in the properties or the format toolbar (font, size, Ctrl+B/I/U, alignment) |
| Delete / duplicate | Del / Ctrl+D, right-click for the context menu |
| Stacking order | Ctrl+] / Ctrl+[ or drag in the object list |
| Zoom | Ctrl+mouse wheel, Ctrl++ / Ctrl+- / Ctrl+0 (automatic), slider in the status bar |
| Print | Ctrl+P or the blue “Print” button |

Changing the left/right margin moves all objects along, so they keep their distance from it.

With “Automatic size” switched on, the text fills the tape height and is centered vertically.
Changing the size by hand switches the automatic off.

An empty frame can only be clicked on its outline, so the objects inside it stay reachable.

### Placeholders

| Placeholder | Result |
|---|---|
| `{nr}` | running number; start value under “Start {nr} at”, every copy counts up by one |
| `{nr:03}` | with leading zeros: 001, 002, … |
| `{date}` / `{date:%d/%m/%y}` | today's date (format codes as in Python's `strftime`) |
| `{time}` / `{time:%H:%M:%S}` | time of day |

The German names `{datum}` and `{zeit}` work as well.

### Cable flags

“File → New cable flag” (Ctrl+Shift+N) or “Label type: Cable flag” in the Label panel creates a
label that is wrapped around a cable; the two ends are stuck together back to back:

```
| flag | ← around the cable (π × diameter + 1 mm) → | flag |
```

You design the flag once, PT-Label prints it twice with the part for the cable in between. Set the
cable diameter in the Label panel; the length of a flag follows its content or can be fixed. Short
fold marks show where to fold (can be switched off). Both flags can be selected and edited in the
preview. With `{nr}` and several copies you get numbered flags such as `K-001`, `K-002`, …
Flexible ID tape (TZe-FX…) wraps best around round cables.

![Cable flag](https://raw.githubusercontent.com/shaag7967/ptlabel/main/docs/screenshots/cable-flag.png)

### Cable wraps

“File → New cable wrap” or “Label type: Cable wrap” creates a label that is wound around the cable.
The design (by default a text turned across the tape, so it reads along the cable) is repeated
evenly over the whole length, so it can be read from every side. The length is
π × diameter × turns; 1.5 turns hold well. The Label panel shows how many repetitions fit.

![Cable wrap](https://raw.githubusercontent.com/shaag7967/ptlabel/main/docs/screenshots/cable-wrap.png)

### Series printing from a table

“File → Series printing from CSV…” links a table to the label; every row becomes one label. Use the
column names as placeholders, e.g. `{Cable}` or `{From} – {To}` (“Insert field” in the Data panel adds
them to the selected text, QR code or barcode). Click a row to see it in the preview; “Print only the
selected rows” limits the job. CSV files from Excel or LibreOffice work as they are (separator `;`,
`,` or tab, UTF-8 or Windows encoding, first row = column names). The link is saved with the label,
and `{nr}` keeps counting from label to label.

![Series printing](https://raw.githubusercontent.com/shaag7967/ptlabel/main/docs/screenshots/series.png)

### Barcodes

EAN-13, EAN-8 and UPC-A are drawn in the usual retail layout (longer guard bars, digits in groups,
standard quiet zones); the check digit is added automatically. The properties panel shows which
content the selected barcode type expects, and switching to a type that cannot encode the current
content fills in an example.

### Fonts

All fonts installed on the system are available. PT-Label also ships with three fonts under the
SIL Open Font License that suit labels well: **Atkinson Hyperlegible** (very legible),
**Barlow Condensed** (narrow, fits more text) and **JetBrains Mono** (monospaced, for serial numbers).

Fonts that cannot print Latin text are hidden from the font lists: fonts for other scripts (Arabic,
Hebrew, Thai, …) that would only print empty boxes, and symbol fonts such as Dingbats. PT-Label tests
every font once when it scans the font folders. “Fonts → Show all fonts” lists them anyway.

Characters that the chosen font does not contain – arrows, check marks, Greek, CJK, … – are taken
automatically from another installed font that has them (fonts with a large character set such as
DejaVu Sans or Noto Sans first), in the same weight and on the same baseline. If no installed font
has a character, the status bar names it.

The “Fonts” menu adds more; every font list shows the fonts in their own typeface:

- **Add font files…** copies `.ttf`/`.otf` files into PT-Label's own font folder, without installing
  them system-wide.
- **Download Google Fonts…** searches the Google Fonts collection (via [Fontsource](https://fontsource.org)),
  shows a preview and installs the regular and bold styles, upright and italic. The files contain the
  Latin character set (Western and Central European languages incl. umlauts and €).
![Google Fonts](https://raw.githubusercontent.com/shaag7967/ptlabel/main/docs/screenshots/fonts.png)

- **Open font folder** shows that folder (`~/.local/share/ptlabel/fonts` on Linux,
  `%APPDATA%\ptlabel\fonts` on Windows).

## Command line

```sh
ptlabel                                   # user interface
ptlabel discover                          # search the network for printers
ptlabel status                            # tape, colors, errors
ptlabel text "Hello world"                # text label sized to the loaded tape
ptlabel text "Line 1" "Line 2" --bold
ptlabel text "Server 1" --qr "https://intranet/server1"
ptlabel text "Test" --preview preview.png         # preview only, no printing
ptlabel print cable.ptlabel --copies 10 --start 1
ptlabel cable "SW01-P12"                  # cable flag for a 6 mm cable
ptlabel cable "SW01-P12" --diameter 8 --length 30   # 8 mm cable, flags 30 mm long
ptlabel cable "K-{nr:03}" --copies 50 --start 1     # numbered series
ptlabel wrap "K-001" --diameter 8                   # cable wrap, text across the tape
ptlabel cable "{Cable}" --csv cables.csv            # one cable flag per row of the table
ptlabel text "{Name}" "{Room}" --csv people.csv --rows 2-5
ptlabel print template.ptlabel --csv cables.csv     # saved label with placeholders
```

Without `--printer` the printer set in the user interface is used. `--printer` also accepts
`file:job.bin` (write the print data to a file) and, on Linux, `/dev/usb/lp0` for a printer
connected via USB.

## Development

```sh
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/ptlabel           # run the program
.venv/bin/pytest            # tests
.venv/bin/python -m build   # wheel and source package in dist/
.venv/bin/python tools/make_screenshots.py   # README screenshots in docs/screenshots
```

### Translations

Texts in the code are English and wrapped in `tr()` (or `ntr()` for plurals) from
`ptlabel.i18n`. Translations are gettext catalogs in `src/ptlabel/locale`. After changing texts:

```sh
.venv/bin/pybabel extract -k tr -k ntr:1,2 --no-location --sort-output -o src/ptlabel/locale/ptlabel.pot src/ptlabel
.venv/bin/pybabel update -i src/ptlabel/locale/ptlabel.pot -d src/ptlabel/locale -D ptlabel
# translate the new entries in src/ptlabel/locale/de/LC_MESSAGES/ptlabel.po, then:
.venv/bin/pybabel compile -d src/ptlabel/locale -D ptlabel
```

A new language is added with `pybabel init -i src/ptlabel/locale/ptlabel.pot -d src/ptlabel/locale -D ptlabel -l <code>`.
The compiled `.mo` files are part of the repository, so no build step is needed.

## Technical notes

- **Printing:** Brother raster protocol (“Raster Command Reference PT-E550W/P750W/P710BT”) sent as
  raw data to TCP port 9100. Every dot in feed direction is one raster line of 128 pins, compressed
  with TIFF PackBits. Resolution 180 dpi, with “High resolution” 360 dpi in feed direction. The
  margin is then also given in 360 dpi dots; this was measured on the device.
- **Status:** SNMP (UDP 161, community `public`), Brother OID `1.3.6.1.4.1.2435.3.3.9.1.6.1.0`,
  which returns the 32-byte status block of the raster protocol. Printer discovery sends an SNMP
  request as broadcast.
- **Printable area per tape** (pins out of 128): 3.5 mm → 24, 6 mm → 32, 9 mm → 50, 12 mm → 70,
  18 mm → 112, 24 mm → 128.
- Dependencies: Pillow (rendering), segno (QR codes), python-barcode (barcode patterns),
  PySide6 (user interface).

### Project layout

```
src/ptlabel/
  tapes.py     tape widths, printable area, color codes
  raster.py    print jobs in Brother raster format, PackBits
  snmp.py      minimal SNMP client (GET, broadcast discovery)
  printer.py   status decoding, sending via TCP 9100 / file
  model.py     label and objects, file format, placeholders
  render.py    label → bitmap
  layouts.py   cable flags and cable wraps (the design arranged several times)
  result.py    render result: bitmap and object positions
  merge.py     series printing: CSV tables, row selection
  barcodes.py  barcode encoding and retail layout
  fonts.py     font discovery (system, bundled and user fonts)
  webfonts.py  Google Fonts download via Fontsource
  i18n.py      translations (gettext)
  cli.py       command line interface
  gui/         PySide6 user interface
    document.py        DocumentController: the edited label, undo, selection, commands
    printing.py        PrinterController: status polling, discovery, print jobs
    print_workflow.py  confirmations and messages around printing
    window.py          main window: assembles everything, files, fonts
    menus.py           menu bar, context menu, main toolbar
    actions.py         all actions with icons and shortcuts
    canvas.py          label preview: ruler, selection, dragging, resizing
    snapping.py        guides and snapping while dragging
    properties.py      property editor of the selected object
    label_panel.py, print_panel.py, objects_panel.py, data_panel.py   dock contents
    format_toolbar.py  font, size, style and alignment of texts
    statusbar.py       printer state, tape, label size, zoom
    theme.py, icons.py light/dark theme, SVG icons in the palette color
    fontui.py          font previews and Google Fonts dialog
  data/fonts/  bundled fonts (SIL Open Font License, see OFL.txt in each folder)
  data/icons/  Lucide icons (ISC license)
  locale/      translations
tests/         unit tests: pytest
tools/         make_screenshots.py
docs/          screenshots
```

## Known limitations

- Tested with the PT-P750W. Models with the same raster protocol (PT-E550W, PT-P710BT) should
  work as well; the PT-P900W/P950NW (360 dpi) and the QL series are not supported.
- P-touch Editor files (`.lbx`) cannot be imported.
- On Windows printing works over the network only, not via USB.

## License

MIT, see [LICENSE](https://github.com/shaag7967/ptlabel/blob/main/LICENSE). The bundled fonts are licensed under the SIL Open Font License 1.1
(see the `OFL.txt` next to each font), the icons come from [Lucide](https://lucide.dev) (ISC license,
see [src/ptlabel/data/icons/LICENSE](https://github.com/shaag7967/ptlabel/blob/main/src/ptlabel/data/icons/LICENSE)).
