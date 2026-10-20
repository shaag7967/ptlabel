# PT-Label – Etiketten-Editor für den Brother PT-P750W

Python-Anwendung zum Gestalten und Drucken von Etiketten auf dem Brother PT-P750W über WLAN.
Läuft unter Windows und Linux und braucht weder P-touch Editor noch den Brother-Treiber.

## Funktionen

- Editor mit WYSIWYG-Vorschau in den Farben des eingelegten Bandes; nicht druckbare Bereiche sind grau.
- Objekte: Text (mehrzeilig, Schriftart, fett/kursiv/unterstrichen, invertiert, Ausrichtung, automatische
  Größe), QR-Code, Barcode (Code 128, Code 39, EAN-13, EAN-8, UPC-A, ITF, Codabar), Bild (PNG/JPG/…,
  Schwellwert oder Rasterung), Rahmen, Linie. Objekte lassen sich um 90°-Schritte drehen.
- Verschieben mit der Maus oder den Pfeiltasten; Größe über den Anfasser unten rechts ändern;
  Rückgängig/Wiederholen.
- Bandbreiten 3,5 / 6 / 9 / 12 / 18 / 24 mm, automatische oder feste Etikettlänge, Ränder.
- Druckoptionen: Kopien, automatisch schneiden, Halbschnitt, Kettendruck, Spiegeln, hohe Auflösung.
- Platzhalter für Seriennummern und Datum: `{nr}`, `{nr:03}`, `{datum}`, `{zeit}`.
- Druckerstatus (Band, Farben, Fehler wie „Abdeckung offen“) wird live abgefragt.
- Drucker werden im Netzwerk automatisch gefunden.
- Etiketten werden als `.ptlabel` gespeichert (JSON, Bilder eingebettet). Export als PNG.
- Kommandozeile für schnelle Etiketten und Skripte.

## Installation und Start

### Windows

Python 3.10 oder neuer installieren und dann **`PT-Label.bat`** doppelklicken.
Beim ersten Start wird `.venv` angelegt und die Pakete aus `requirements.txt` werden installiert.

### Linux (Debian/Ubuntu)

```sh
sudo apt install python3-venv python3-tk fonts-dejavu
chmod +x pt-label.sh
./pt-label.sh
```

Alternativ systemweit: `pip install .` – danach steht der Befehl `ptlabel` zur Verfügung.

### Drucker

Der Drucker muss eingeschaltet und im WLAN sein. Beim ersten Start sucht PT-Label ihn selbst.
Sonst unter „Drucken → Drucker“ den Hostnamen (`BRW…` gefolgt von der MAC-Adresse, steht auf dem
Netzwerk-Konfigurationsausdruck) oder die IP-Adresse eintragen. Der PT-P750W schaltet sich nach einiger Zeit ohne Nutzung ab.
Danach meldet die Statuszeile „antwortet nicht“, bis er wieder eingeschaltet ist.

## Bedienung

| Aktion | Wie |
|---|---|
| Objekt einfügen | Werkzeugleiste „+ Text“, „+ QR-Code“ … oder Menü „Einfügen“ |
| Verschieben | Ziehen mit der Maus, Pfeiltasten 0,5 mm, Umschalt+Pfeil 0,1 mm |
| Größe ändern | weißes Quadrat unten rechts am markierten Objekt ziehen |
| Text bearbeiten | Doppelklick auf das Objekt oder Feld „Text“ rechts |
| Löschen / Duplizieren | Entf / Strg+D, Rechtsklick für Kontextmenü |
| Zoom | Strg+Mausrad, Strg++ / Strg+- |
| Drucken | Strg+P oder „Drucken“ |

Ist „Größe automatisch“ eingeschaltet, füllt der Text die Bandhöhe und wird senkrecht zentriert.
Sobald Sie die Größe von Hand ändern, wird die Automatik abgeschaltet.

Ein leerer Rahmen lässt sich nur an seiner Linie anklicken. So bleiben die Objekte darin erreichbar.

### Platzhalter

| Platzhalter | Ergebnis |
|---|---|
| `{nr}` | laufende Nummer; Startwert unter „Nummer {nr} ab“, jede Kopie zählt eins weiter |
| `{nr:03}` | mit führenden Nullen: 001, 002, … |
| `{datum}` / `{datum:%d.%m.%y}` | heutiges Datum (Format wie bei Python `strftime`) |
| `{zeit}` / `{zeit:%H:%M:%S}` | Uhrzeit |

## Kommandozeile

Unter Windows `.venv\Scripts\python.exe -m ptlabel …`, unter Linux `.venv-linux/bin/python -m ptlabel …`.

```sh
ptlabel                                   # grafische Oberfläche
ptlabel discover                          # Drucker im Netzwerk suchen
ptlabel status                            # Band, Farben, Fehler
ptlabel text "Hallo Welt"                 # Text-Etikett, Größe passend zum eingelegten Band
ptlabel text "Zeile 1" "Zeile 2" --bold
ptlabel text "Server 1" --qr "https://intranet/server1"
ptlabel text "Probe" --preview vorschau.png       # nur Vorschau, kein Druck
ptlabel print kabel.ptlabel --copies 10 --start 1
```

Ohne `--printer` wird der in der Oberfläche eingestellte Drucker benutzt.
`--printer` akzeptiert außerdem `file:job.bin` (Druckdaten in eine Datei schreiben) und unter Linux
`/dev/usb/lp0` für einen per USB angeschlossenen Drucker.

## Technik

- **Druck:** Brother-Raster-Protokoll („Raster Command Reference PT-E550W/P750W/P710BT“) als Rohdaten
  an TCP-Port 9100. Pro Druckpunkt in Bandrichtung wird eine Rasterzeile mit 128 Nadeln gesendet,
  komprimiert mit TIFF PackBits. Druckauflösung 180 dpi, mit „Hohe Auflösung“ 360 dpi in Bandrichtung.
  Der Rand wird dann ebenfalls in 360-dpi-Punkten angegeben; das ist am Gerät nachgemessen.
- **Status:** SNMP (UDP 161, Community `public`), Brother-OID `1.3.6.1.4.1.2435.3.3.9.1.6.1.0`.
  Sie liefert den 32-Byte-Statusblock des Raster-Protokolls. Die Druckersuche sendet eine
  SNMP-Anfrage per Broadcast.
- **Druckbereich je Band** (Nadeln von 128): 3,5 mm → 24, 6 mm → 32, 9 mm → 50, 12 mm → 70,
  18 mm → 112, 24 mm → 128.
- Abhängigkeiten: Pillow (Rendering), segno (QR-Codes), python-barcode (Barcode-Muster). Die
  Oberfläche nutzt Tkinter aus der Standardbibliothek.

### Aufbau

```
ptlabel/
  tapes.py    Bandbreiten, Druckbereich, Farbcodes
  raster.py   Druckauftrag im Brother-Raster-Format, PackBits
  snmp.py     minimaler SNMP-Client (GET, Broadcast-Suche)
  printer.py  Status-Auswertung, Senden über TCP 9100 / Datei
  model.py    Etikett und Objekte, Dateiformat, Platzhalter
  render.py   Etikett → Bitmap
  fonts.py    Schriftarten unter Windows und Linux finden
  gui.py      Tkinter-Oberfläche
  cli.py      Kommandozeile
tests/        Unit-Tests: python -m unittest discover -s tests
```

## Bekannte Grenzen

- P-touch-Editor-Dateien (`.lbx`) können nicht importiert werden.
- Unter Windows wird nur über das Netzwerk gedruckt, nicht über USB.
