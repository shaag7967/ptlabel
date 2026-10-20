"""Tkinter user interface (Windows and Linux)."""

from __future__ import annotations

import base64
import io
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

from PIL import Image, ImageDraw, ImageTk

from . import __version__, config, fonts
from .model import (PLACEHOLDER_HELP, BarcodeObject, FrameObject, ImageObject, LabelDocument, LabelObject,
                    LineObject, Prop, QRCodeObject, TextObject)
from .printer import (NetworkPrinter, PrinterError, PrinterStatus, discover_printers, open_printer,
                      wait_for_completion)
from .raster import build_job
from .render import Placed, RenderResult, image_aspect, print_pages, render
from .tapes import DPI, MM_PER_INCH, TAPES

APP_NAME = "PT-Label"
FILE_TYPES = [("PT-Label-Etikett", "*.ptlabel"), ("Alle Dateien", "*.*")]
IMAGE_TYPES = [("Bilder", "*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp"), ("Alle Dateien", "*.*")]
INSERT_ITEMS = [("Text", "text"), ("QR-Code", "qrcode"), ("Barcode", "barcode"), ("Bild…", "image"),
                ("Rahmen", "frame"), ("Linie", "line")]
PRINT_FLAGS = [
    ("auto_cut", "Automatisch schneiden"),
    ("half_cut", "Halbschnitt zwischen Etiketten"),
    ("chain", "Kettendruck (spart Band, letztes\nEtikett bleibt im Gerät)"),
    ("mirror", "Spiegeln"),
    ("high_res", "Hohe Auflösung 180×360 dpi"),
]
RULER_H = 24
PAD = 24
HANDLE = 9
STATUS_INTERVAL_MS = 20000
MAX_IMAGE_PX = 1200
SHADE = (40, 40, 40)
ACCENT = "#0a64d8"
COLOR_OK = "#1e7b34"
COLOR_ERROR = "#b00020"
COLOR_INFO = "#444444"
COLOR_WARN = "#9a5b00"


def _fmt(value: float) -> str:
    return f"{round(float(value), 2):g}"


def _parse_float(text: str) -> float | None:
    try:
        return float(str(text).replace(",", ".").strip())
    except ValueError:
        return None


def _rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def _index_of(items: list, obj) -> int | None:
    """Index by identity (dataclass equality would confuse identical copies)."""
    return next((i for i, item in enumerate(items) if item is obj), None)


class ScrollFrame(ttk.Frame):
    """Vertically scrollable container; widgets go into ``.inner``."""

    def __init__(self, master, width: int = 330):
        super().__init__(master)
        background = ttk.Style(self).lookup("TFrame", "background") or None
        self.canvas = tk.Canvas(self, width=width, highlightthickness=0, borderwidth=0, background=background)
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = ttk.Frame(self.canvas)
        self._window = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._window, width=e.width))
        self.bind("<Enter>", self._bind_wheel)
        self.bind("<Leave>", self._unbind_wheel)

    def _bind_wheel(self, _event):
        self.bind_all("<MouseWheel>", self._on_wheel)
        self.bind_all("<Button-4>", self._on_wheel)
        self.bind_all("<Button-5>", self._on_wheel)

    def _unbind_wheel(self, _event):
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.unbind_all(sequence)

    def _on_wheel(self, event):
        if self.inner.winfo_reqheight() <= self.canvas.winfo_height():
            return
        up = event.num == 4 or getattr(event, "delta", 0) > 0
        self.canvas.yview_scroll(-2 if up else 2, "units")


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.cfg = config.load()
        self.doc = LabelDocument()
        self.path: Path | None = None
        self.selected: LabelObject | None = None
        self.result: RenderResult | None = None
        self.status: PrinterStatus | None = None
        self.zoom = int(self.cfg.get("zoom") or 0)  # 0 = automatic
        self._photo = None
        self._origin = (PAD, RULER_H + PAD)
        self._drag: dict | None = None
        self._undo: list[str] = []
        self._undo_pos = -1
        self._saved_state = ""
        self._commit_job = None
        self._render_job = None
        self._syncing = False
        self._busy = False
        self._status_pending = False
        self._tape_checked = False
        self._bg_queue: queue.Queue = queue.Queue()
        self._prop_vars: dict[str, tuple[Prop, tk.Variable]] = {}
        self._prop_widgets: dict[str, tk.Widget] = {}
        self._text_widgets: dict[str, tk.Text] = {}

        fonts.REGISTRY.ensure_loaded()
        self._syncing = True  # ignore variable traces while widgets are created
        self._build_ui()
        self._syncing = False
        self._bind_keys()
        self.new_document(confirm=False)
        root.protocol("WM_DELETE_WINDOW", self.quit)
        root.after(100, self._poll_bg)
        root.after(300, self._startup_printer)

    # ------------------------------------------------------------------ UI setup

    def _build_ui(self) -> None:
        root = self.root
        root.title(APP_NAME)
        root.geometry(self.cfg.get("geometry") or "1280x720")
        root.minsize(900, 520)
        style = ttk.Style(root)
        if sys.platform.startswith("linux") and "clam" in style.theme_names():
            style.theme_use("clam")
        self._bold = tkfont.nametofont("TkDefaultFont").copy()
        self._bold.configure(weight="bold")
        style.configure("Print.TButton", font=self._bold, padding=(14, 6))
        self._set_icon()

        self._build_menu()
        self._build_toolbar()
        self._build_statusbar()

        body = ttk.PanedWindow(root, orient="horizontal")
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body)
        self.canvas = tk.Canvas(left, background="#7d838b", highlightthickness=0, takefocus=1)
        xbar = ttk.Scrollbar(left, orient="horizontal", command=self.canvas.xview)
        ybar = ttk.Scrollbar(left, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=xbar.set, yscrollcommand=ybar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        body.add(left, weight=1)

        side = ScrollFrame(body)
        body.add(side, weight=0)
        self._build_label_panel(side.inner)
        self.props_frame = ttk.LabelFrame(side.inner, text="Objekt", padding=8)
        self.props_frame.pack(fill="x", padx=6, pady=3)
        self._build_print_panel(side.inner)

    def _set_icon(self) -> None:
        icon = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(icon)
        draw.rounded_rectangle((2, 16, 61, 47), radius=6, fill=(248, 214, 22), outline=(60, 60, 60), width=2)
        draw.rectangle((12, 26, 50, 29), fill=(20, 20, 20))
        draw.rectangle((12, 34, 40, 37), fill=(20, 20, 20))
        self._icon = ImageTk.PhotoImage(icon)
        self.root.iconphoto(True, self._icon)

    def _build_menu(self) -> None:
        menu = tk.Menu(self.root)
        file = tk.Menu(menu, tearoff=False)
        file.add_command(label="Neu", accelerator="Strg+N", command=self.new_document)
        file.add_command(label="Öffnen…", accelerator="Strg+O", command=self.open_document)
        file.add_command(label="Speichern", accelerator="Strg+S", command=self.save_document)
        file.add_command(label="Speichern unter…", accelerator="Strg+Umschalt+S", command=self.save_document_as)
        file.add_separator()
        file.add_command(label="Als PNG exportieren…", command=self.export_png)
        file.add_separator()
        file.add_command(label="Beenden", command=self.quit)
        menu.add_cascade(label="Datei", menu=file)

        edit = tk.Menu(menu, tearoff=False)
        self._fill_edit_menu(edit)
        menu.add_cascade(label="Bearbeiten", menu=edit)

        insert = tk.Menu(menu, tearoff=False)
        for label, kind in INSERT_ITEMS:
            insert.add_command(label=label, command=lambda k=kind: self.insert(k))
        menu.add_cascade(label="Einfügen", menu=insert)

        view = tk.Menu(menu, tearoff=False)
        view.add_command(label="Vergrößern", accelerator="Strg++", command=lambda: self.set_zoom(self._zoom() + 1))
        view.add_command(label="Verkleinern", accelerator="Strg+-", command=lambda: self.set_zoom(self._zoom() - 1))
        view.add_command(label="Automatisch", command=lambda: self.set_zoom(0))
        menu.add_cascade(label="Ansicht", menu=view)

        printer = tk.Menu(menu, tearoff=False)
        printer.add_command(label="Drucken", accelerator="Strg+P", command=self.print_label)
        printer.add_command(label="Status abfragen", command=lambda: self.refresh_status(manual=True))
        printer.add_command(label="Drucker suchen…", command=self.discover)
        menu.add_cascade(label="Drucker", menu=printer)

        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="Platzhalter…", command=lambda: messagebox.showinfo(
            "Platzhalter", "In Texten, QR-Codes und Barcodes verwendbar:\n\n" + PLACEHOLDER_HELP))
        help_menu.add_command(label="Bedienung…", command=self.show_usage)
        help_menu.add_command(label="Über…", command=lambda: messagebox.showinfo(
            APP_NAME, f"{APP_NAME} {__version__}\nEtiketten-Editor für Brother PT-P750W"))
        menu.add_cascade(label="Hilfe", menu=help_menu)
        self.root.configure(menu=menu)

        self.context_menu = tk.Menu(self.root, tearoff=False)
        self._fill_edit_menu(self.context_menu, history=False)

    def _fill_edit_menu(self, menu: tk.Menu, history: bool = True) -> None:
        if history:
            menu.add_command(label="Rückgängig", accelerator="Strg+Z", command=self.undo)
            menu.add_command(label="Wiederholen", accelerator="Strg+Y", command=self.redo)
            menu.add_separator()
        menu.add_command(label="Duplizieren", accelerator="Strg+D", command=self.duplicate)
        menu.add_command(label="Löschen", accelerator="Entf", command=self.delete_selected)
        menu.add_separator()
        menu.add_command(label="Nach vorne", command=lambda: self.restack(1))
        menu.add_command(label="Nach hinten", command=lambda: self.restack(-1))
        menu.add_command(label="Vertikal zentrieren", command=self.center_vertically)

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self.root, padding=(6, 4))
        bar.pack(side="top", fill="x")

        def button(text, command):
            ttk.Button(bar, text=text, command=command).pack(side="left", padx=1)

        def separator():
            ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6, pady=2)

        button("Neu", self.new_document)
        button("Öffnen", self.open_document)
        button("Speichern", self.save_document)
        separator()
        for label, kind in INSERT_ITEMS:
            button("+ " + label.rstrip("…"), lambda k=kind: self.insert(k))
        separator()
        button("Duplizieren", self.duplicate)
        button("Löschen", self.delete_selected)
        separator()
        button("−", lambda: self.set_zoom(self._zoom() - 1))
        self.lbl_zoom = ttk.Label(bar, width=8, anchor="center")
        self.lbl_zoom.pack(side="left")
        button("+", lambda: self.set_zoom(self._zoom() + 1))
        ttk.Button(bar, text="Drucken", style="Print.TButton", command=self.print_label).pack(side="right")

    def _build_statusbar(self) -> None:
        bar = ttk.Frame(self.root, padding=(8, 3))
        bar.pack(side="bottom", fill="x")
        self.lbl_printer = ttk.Label(bar, text="Drucker: –")
        self.lbl_printer.pack(side="left")
        self.btn_adopt = ttk.Button(bar, text="Band übernehmen", command=self.adopt_tape)
        self.lbl_size = ttk.Label(bar, text="")
        self.lbl_size.pack(side="right")
        self.lbl_warning = ttk.Label(bar, text="", foreground=COLOR_WARN)
        self.lbl_warning.pack(side="right", padx=12)
        self.lbl_message = ttk.Label(bar, text="")
        self.lbl_message.pack(side="left", padx=12)

    def _build_label_panel(self, parent) -> None:
        frame = ttk.LabelFrame(parent, text="Etikett", padding=8)
        frame.pack(fill="x", padx=6, pady=(6, 3))
        frame.columnconfigure(1, weight=1)
        self.v_tape = tk.StringVar()
        self.v_auto_length = tk.BooleanVar()
        self.v_length = tk.StringVar()
        self.v_margin = tk.StringVar()
        ttk.Label(frame, text="Bandbreite").grid(row=0, column=0, sticky="w", pady=2)
        ttk.Combobox(frame, textvariable=self.v_tape, values=[t.label for t in TAPES], state="readonly",
                     width=10).grid(row=0, column=1, sticky="ew", pady=2)
        self.lbl_print_area = ttk.Label(frame, foreground=COLOR_INFO)
        self.lbl_print_area.grid(row=1, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(frame, text="Länge automatisch", variable=self.v_auto_length).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=2)
        ttk.Label(frame, text="Länge (mm)").grid(row=3, column=0, sticky="w", pady=2)
        self.sp_length = ttk.Spinbox(frame, from_=5, to=1000, increment=1, textvariable=self.v_length, width=8)
        self.sp_length.grid(row=3, column=1, sticky="ew", pady=2)
        ttk.Label(frame, text="Rand links/rechts (mm)").grid(row=4, column=0, sticky="w", pady=2, padx=(0, 6))
        ttk.Spinbox(frame, from_=1, to=50, increment=0.5, textvariable=self.v_margin, width=8).grid(
            row=4, column=1, sticky="ew", pady=2)
        for var in (self.v_tape, self.v_auto_length, self.v_length, self.v_margin):
            var.trace_add("write", self._on_label_vars)

    def _build_print_panel(self, parent) -> None:
        frame = ttk.LabelFrame(parent, text="Drucken", padding=8)
        frame.pack(fill="x", padx=6, pady=(3, 6))
        frame.columnconfigure(1, weight=1)
        ttk.Label(frame, text="Drucker").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.v_printer = tk.StringVar(value=self.cfg.get("printer", ""))
        entry = ttk.Entry(frame, textvariable=self.v_printer, width=18)
        entry.grid(row=0, column=1, sticky="ew")
        entry.bind("<Return>", lambda e: self._printer_changed())
        entry.bind("<FocusOut>", lambda e: self._printer_changed())
        ttk.Button(frame, text="Suchen…", command=self.discover).grid(row=0, column=2, padx=(4, 0))
        self.lbl_status = ttk.Label(frame, text="", wraplength=280, justify="left")
        self.lbl_status.grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 8))

        self.v_copies = tk.StringVar()
        self.v_counter = tk.StringVar()
        ttk.Label(frame, text="Kopien").grid(row=2, column=0, sticky="w", pady=2)
        ttk.Spinbox(frame, from_=1, to=999, increment=1, textvariable=self.v_copies, width=7).grid(
            row=2, column=1, sticky="w", pady=2)
        ttk.Label(frame, text="Nummer {nr} ab").grid(row=3, column=0, sticky="w", pady=2)
        ttk.Spinbox(frame, from_=0, to=999999, increment=1, textvariable=self.v_counter, width=7).grid(
            row=3, column=1, sticky="w", pady=2)
        self.v_flags: dict[str, tk.BooleanVar] = {}
        for row, (attr, text) in enumerate(PRINT_FLAGS, start=4):
            var = tk.BooleanVar()
            ttk.Checkbutton(frame, text=text, variable=var).grid(row=row, column=0, columnspan=3, sticky="w", pady=1)
            self.v_flags[attr] = var
            var.trace_add("write", self._on_print_vars)
        ttk.Button(frame, text="Drucken", style="Print.TButton", command=self.print_label).grid(
            row=len(PRINT_FLAGS) + 4, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        self.v_copies.trace_add("write", self._on_print_vars)
        self.v_counter.trace_add("write", self._on_print_vars)

    def _bind_keys(self) -> None:
        root, canvas = self.root, self.canvas
        root.bind("<Control-n>", lambda e: self.new_document())
        root.bind("<Control-o>", lambda e: self.open_document())
        root.bind("<Control-s>", lambda e: self.save_document())
        root.bind("<Control-S>", lambda e: self.save_document_as())
        root.bind("<Control-p>", lambda e: self.print_label())
        root.bind("<Control-z>", lambda e: self._unless_editing(self.undo))
        root.bind("<Control-y>", lambda e: self._unless_editing(self.redo))
        root.bind("<Control-d>", lambda e: self._unless_editing(self.duplicate))
        root.bind("<Control-plus>", lambda e: self.set_zoom(self._zoom() + 1))
        root.bind("<Control-equal>", lambda e: self.set_zoom(self._zoom() + 1))
        root.bind("<Control-minus>", lambda e: self.set_zoom(self._zoom() - 1))
        canvas.bind("<ButtonPress-1>", self._on_press)
        canvas.bind("<B1-Motion>", self._on_motion)
        canvas.bind("<ButtonRelease-1>", self._on_release)
        canvas.bind("<Double-Button-1>", self._on_double)
        canvas.bind("<Button-3>", self._on_context)
        canvas.bind("<Delete>", lambda e: self.delete_selected())
        canvas.bind("<BackSpace>", lambda e: self.delete_selected())
        for key, (dx, dy) in {"Left": (-1, 0), "Right": (1, 0), "Up": (0, -1), "Down": (0, 1)}.items():
            canvas.bind(f"<{key}>", lambda e, d=(dx, dy): self.nudge(d[0] * 0.5, d[1] * 0.5))
            canvas.bind(f"<Shift-{key}>", lambda e, d=(dx, dy): self.nudge(d[0] * 0.1, d[1] * 0.1))
        canvas.bind("<MouseWheel>", self._on_wheel)
        canvas.bind("<Button-4>", self._on_wheel)
        canvas.bind("<Button-5>", self._on_wheel)
        canvas.bind("<Configure>", lambda e: self.redraw())

    def _unless_editing(self, action) -> str | None:
        try:
            focus = self.root.focus_get()
        except (KeyError, tk.TclError):
            focus = None
        if isinstance(focus, (tk.Text, tk.Entry, ttk.Entry)):
            return None  # let the widget handle its own shortcut
        action()
        return "break"

    # ------------------------------------------------------------------ background work

    def run_bg(self, work, done=None) -> None:
        def worker():
            try:
                result, error = work(), None
            except Exception as exc:
                result, error = None, exc
            self._bg_queue.put((done, result, error))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_bg(self) -> None:
        try:
            while True:
                done, result, error = self._bg_queue.get_nowait()
                if done:
                    done(result, error)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_bg)

    # ------------------------------------------------------------------ document state

    def new_document(self, confirm: bool = True) -> None:
        if confirm and not self._confirm_discard():
            return
        tape_mm = self.status.tape.width_mm if self.status and self.status.tape else 12.0
        self.doc = LabelDocument(tape_mm=tape_mm)
        self.doc.objects.append(TextObject(x=self.doc.margin_mm, font=fonts.REGISTRY.default_family()))
        self.path = None
        self._load_state()
        self.select(self.doc.objects[0])

    def _load_state(self) -> None:
        state = self.doc.to_json()
        self._undo = [state]
        self._undo_pos = 0
        self._saved_state = state
        self.selected = None
        self._sync_label_panel()
        self._sync_print_panel()
        self._build_props()
        self._update_tape_warning()
        self._update_title()
        self.redraw()

    def _is_modified(self) -> bool:
        return self.doc.to_json() != self._saved_state

    def _is_pristine(self) -> bool:
        return self.path is None and len(self._undo) == 1 and not self._is_modified()

    def _confirm_discard(self) -> bool:
        self._flush_commit()
        if not self._is_modified():
            return True
        answer = messagebox.askyesnocancel(APP_NAME, "Das Etikett wurde geändert. Änderungen speichern?")
        if answer is None:
            return False
        return self.save_document() if answer else True

    def _update_title(self) -> None:
        name = self.path.name if self.path else "Unbenannt"
        self.root.title(f"{'*' if self._is_modified() else ''}{name} – {APP_NAME}")

    def changed(self) -> None:
        """Call after every modification of the document."""
        self.redraw()
        if self._commit_job is not None:
            self.root.after_cancel(self._commit_job)
        self._commit_job = self.root.after(500, self.commit)

    def commit(self) -> None:
        if self._commit_job is not None:
            self.root.after_cancel(self._commit_job)
            self._commit_job = None
        state = self.doc.to_json()
        if self._undo[self._undo_pos] != state:
            del self._undo[self._undo_pos + 1:]
            self._undo.append(state)
            if len(self._undo) > 200:
                del self._undo[0]
            self._undo_pos = len(self._undo) - 1
        self._update_title()

    def _flush_commit(self) -> None:
        if self._commit_job is not None:
            self.commit()

    def undo(self) -> None:
        self._flush_commit()
        if self._undo_pos > 0:
            self._undo_pos -= 1
            self._restore(self._undo[self._undo_pos])

    def redo(self) -> None:
        self._flush_commit()
        if self._undo_pos < len(self._undo) - 1:
            self._undo_pos += 1
            self._restore(self._undo[self._undo_pos])

    def _restore(self, state: str) -> None:
        index = _index_of(self.doc.objects, self.selected)
        self.doc = LabelDocument.from_json(state)
        self.selected = self.doc.objects[index] if index is not None and index < len(self.doc.objects) else None
        self._sync_label_panel()
        self._sync_print_panel()
        self._build_props()
        self._update_tape_warning()
        self._update_title()
        self.redraw()

    # ------------------------------------------------------------------ files

    def _initial_dir(self) -> str:
        if self.path:
            return str(self.path.parent)
        return self.cfg.get("last_dir") or str(Path.home())

    def open_document(self) -> None:
        if not self._confirm_discard():
            return
        name = filedialog.askopenfilename(parent=self.root, title="Etikett öffnen", filetypes=FILE_TYPES,
                                          initialdir=self._initial_dir())
        if not name:
            return
        try:
            doc = LabelDocument.load(name)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            messagebox.showerror(APP_NAME, f"Datei kann nicht geöffnet werden:\n{exc}")
            return
        self.doc = doc
        self.path = Path(name)
        self.cfg["last_dir"] = str(self.path.parent)
        self._load_state()

    def save_document(self) -> bool:
        if self.path is None:
            return self.save_document_as()
        self._flush_commit()
        try:
            self.doc.save(self.path)
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Speichern fehlgeschlagen:\n{exc}")
            return False
        self._saved_state = self.doc.to_json()
        self._update_title()
        self._set_message(f"Gespeichert: {self.path.name}", COLOR_OK)
        return True

    def save_document_as(self) -> bool:
        name = filedialog.asksaveasfilename(parent=self.root, title="Etikett speichern", filetypes=FILE_TYPES,
                                            defaultextension=".ptlabel", initialdir=self._initial_dir())
        if not name:
            return False
        self.path = Path(name)
        self.cfg["last_dir"] = str(self.path.parent)
        return self.save_document()

    def export_png(self) -> None:
        name = filedialog.asksaveasfilename(parent=self.root, title="Als PNG exportieren",
                                            filetypes=[("PNG", "*.png")], defaultextension=".png",
                                            initialdir=self._initial_dir())
        if not name:
            return
        res = render(self.doc)
        tape_rgb, ink_rgb = self._preview_colors()
        img = Image.new("RGB", res.image.size, tape_rgb)
        img.paste(ink_rgb, (0, 0), res.image)
        img = img.resize((img.width * 4, img.height * 4), Image.Resampling.NEAREST)
        try:
            img.save(name, dpi=(DPI * 4, DPI * 4))
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Export fehlgeschlagen:\n{exc}")
            return
        self._set_message(f"Exportiert: {Path(name).name}", COLOR_OK)

    def quit(self) -> None:
        if not self._confirm_discard():
            return
        self.cfg["geometry"] = self.root.geometry()
        self.cfg["zoom"] = self.zoom
        self.cfg["printer"] = self.v_printer.get().strip()
        config.save(self.cfg)
        self.root.destroy()

    # ------------------------------------------------------------------ panels

    def _sync_label_panel(self) -> None:
        self._syncing = True
        try:
            doc = self.doc
            self.v_tape.set(doc.tape.label)
            self.v_auto_length.set(doc.auto_length)
            self.v_length.set(_fmt(doc.length_mm))
            self.v_margin.set(_fmt(doc.margin_mm))
            self.sp_length.configure(state="disabled" if doc.auto_length else "normal")
            self.lbl_print_area.configure(text=f"Druckbereich: {doc.tape.print_mm:.1f} mm hoch")
        finally:
            self._syncing = False

    def _on_label_vars(self, *_) -> None:
        if self._syncing:
            return
        doc = self.doc
        tape = next((t for t in TAPES if t.label == self.v_tape.get()), doc.tape)
        doc.tape_mm = tape.width_mm
        auto = self.v_auto_length.get()
        if doc.auto_length and not auto and self.result:
            doc.length_mm = round(self.result.length_mm, 1)  # start from the current length
            self._syncing = True
            self.v_length.set(_fmt(doc.length_mm))
            self._syncing = False
        doc.auto_length = auto
        length = _parse_float(self.v_length.get())
        if length is not None and 5 <= length <= 2000:
            doc.length_mm = length
        margin = _parse_float(self.v_margin.get())
        if margin is not None and 0.5 <= margin <= 100:
            doc.margin_mm = margin
        self.sp_length.configure(state="disabled" if doc.auto_length else "normal")
        self.lbl_print_area.configure(text=f"Druckbereich: {doc.tape.print_mm:.1f} mm hoch")
        self._update_tape_warning()
        self.changed()

    def _sync_print_panel(self) -> None:
        self._syncing = True
        try:
            self.v_copies.set(str(self.doc.copies))
            self.v_counter.set(str(self.doc.counter_start))
            for attr, var in self.v_flags.items():
                var.set(bool(getattr(self.doc, attr)))
        finally:
            self._syncing = False

    def _on_print_vars(self, *_) -> None:
        if self._syncing:
            return
        copies = _parse_float(self.v_copies.get())
        if copies is not None and 1 <= copies <= 999:
            self.doc.copies = int(copies)
        counter = _parse_float(self.v_counter.get())
        if counter is not None and counter >= 0:
            self.doc.counter_start = int(counter)
        for attr, var in self.v_flags.items():
            setattr(self.doc, attr, bool(var.get()))
        self.changed()

    def _build_props(self) -> None:
        frame = self.props_frame
        for child in frame.winfo_children():
            child.destroy()
        self._prop_vars, self._prop_widgets, self._text_widgets = {}, {}, {}
        obj = self.selected
        if obj is None:
            frame.configure(text="Objekt")
            ttk.Label(frame, text="Kein Objekt ausgewählt.\nObjekt anklicken oder über „Einfügen“\nein neues hinzufügen.",
                      foreground=COLOR_INFO, justify="left").grid(sticky="w")
            return
        frame.configure(text=obj.title)
        frame.columnconfigure(1, weight=1)
        row = 0
        for prop in obj.props():
            row = self._add_prop_widget(frame, obj, prop, row)
        self._update_prop_states()
        self._show_effective_size()

    def _add_prop_widget(self, frame, obj: LabelObject, prop: Prop, row: int) -> int:
        value = getattr(obj, prop.attr)
        if prop.kind == "multiline":
            ttk.Label(frame, text=prop.label).grid(row=row, column=0, columnspan=2, sticky="w")
            text = tk.Text(frame, height=3, width=30, wrap="none", undo=True, font="TkDefaultFont")
            text.insert("1.0", value)
            text.edit_modified(False)
            text.grid(row=row + 1, column=0, columnspan=2, sticky="ew", pady=(0, 6))
            text.bind("<<Modified>>", lambda e, a=prop.attr, w=text: self._on_text_widget(a, w))
            self._text_widgets[prop.attr] = text
            return row + 2
        if prop.kind == "image":
            box = ttk.Frame(frame)
            ttk.Button(box, text="Bild laden…", command=self.load_image_for_selected).pack(side="left")
            ttk.Label(box, text=getattr(obj, "name", "") or "(kein Bild)", foreground=COLOR_INFO).pack(side="left", padx=6)
            box.grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 4))
            return row + 1
        if prop.kind == "bool":
            var = tk.BooleanVar(value=bool(value))
            widget = ttk.Checkbutton(frame, text=prop.label, variable=var)
            widget.grid(row=row, column=0, columnspan=2, sticky="w", pady=1)
        else:
            ttk.Label(frame, text=prop.label).grid(row=row, column=0, sticky="w", pady=1, padx=(0, 6))
            if prop.kind in ("float", "int"):
                var = tk.StringVar(value=_fmt(value))
                lo, hi, step = prop.options
                widget = ttk.Spinbox(frame, from_=lo, to=hi, increment=step, textvariable=var, width=9)
            elif prop.kind == "choice":
                labels = [label for _, label in prop.options]
                var = tk.StringVar(value=next((label for v, label in prop.options if v == value), labels[0]))
                widget = ttk.Combobox(frame, textvariable=var, values=labels, state="readonly", width=14)
            elif prop.kind == "font":
                var = tk.StringVar(value=fonts.REGISTRY.find_family(value or "") or fonts.REGISTRY.default_family())
                widget = ttk.Combobox(frame, textvariable=var, values=fonts.REGISTRY.families(), width=18)
            else:
                var = tk.StringVar(value=str(value))
                widget = ttk.Entry(frame, textvariable=var, width=20)
            widget.grid(row=row, column=1, sticky="ew", pady=1)
        var.trace_add("write", lambda *_, p=prop, v=var: self._on_prop_var(p, v))
        self._prop_vars[prop.attr] = (prop, var)
        self._prop_widgets[prop.attr] = widget
        return row + 1

    def _on_prop_var(self, prop: Prop, var: tk.Variable) -> None:
        obj = self.selected
        if self._syncing or obj is None:
            return
        raw = var.get()
        if prop.kind == "bool":
            value = bool(raw)
        elif prop.kind in ("float", "int"):
            value = _parse_float(raw)
            if value is None or not prop.options[0] <= value <= prop.options[1]:
                return
            if prop.kind == "int":
                value = int(round(value))
        elif prop.kind == "choice":
            value = next((v for v, label in prop.options if label == raw), None)
            if value is None:
                return
        elif prop.kind == "font":
            value = fonts.REGISTRY.find_family(raw)
            if value is None:
                return
        else:
            value = raw
        if isinstance(obj, TextObject) and (prop.attr == "size" or (prop.attr == "auto_size" and not value)):
            self._freeze_auto_text(obj)
        setattr(obj, prop.attr, value)
        if isinstance(obj, ImageObject) and obj.keep_aspect and prop.attr in ("width", "height", "keep_aspect"):
            aspect = image_aspect(obj)
            if aspect:
                if prop.attr == "height":
                    obj.width = round(obj.height * aspect, 1)
                else:
                    obj.height = round(obj.width / aspect, 1)
                self._sync_props(("width", "height"))
        self._update_prop_states()
        self.changed()

    def _on_text_widget(self, attr: str, widget: tk.Text) -> None:
        if not widget.edit_modified():
            return
        widget.edit_modified(False)
        obj = self.selected
        if self._syncing or obj is None:
            return
        value = widget.get("1.0", "end-1c")
        if getattr(obj, attr) != value:
            setattr(obj, attr, value)
            self.changed()

    def _sync_props(self, attrs=None) -> None:
        obj = self.selected
        if obj is None:
            return
        self._syncing = True
        try:
            for attr, (prop, var) in self._prop_vars.items():
                if attrs and attr not in attrs:
                    continue
                value = getattr(obj, attr)
                if prop.kind == "bool":
                    new = bool(value)
                elif prop.kind in ("float", "int"):
                    new = _fmt(value)
                elif prop.kind == "choice":
                    new = next((label for v, label in prop.options if v == value), var.get())
                else:
                    new = value
                if var.get() != new:
                    var.set(new)
            for attr, widget in self._text_widgets.items():
                if attrs and attr not in attrs:
                    continue
                value = getattr(obj, attr)
                if widget.get("1.0", "end-1c") != value:
                    widget.delete("1.0", "end")
                    widget.insert("1.0", value)
                    widget.edit_modified(False)
        finally:
            self._syncing = False

    def _update_prop_states(self) -> None:
        obj = self.selected
        rules = []
        if isinstance(obj, ImageObject):
            rules.append(("threshold", not obj.dither))
        if isinstance(obj, BarcodeObject):
            rules.append(("text_size", obj.show_text))
        if isinstance(obj, TextObject):
            rules.append(("y", not obj.auto_size))
        for attr, enabled in rules:
            widget = self._prop_widgets.get(attr)
            if widget is not None:
                widget.configure(state="normal" if enabled else "disabled")

    def _freeze_auto_text(self, obj: TextObject) -> None:
        """Turn an automatically sized text into a fixed one at its current size and position."""
        placed = self._placed_of(obj)
        if obj.auto_size and placed and self.result:
            obj.size = placed.size_pt or obj.size
            obj.y = round(placed.box[1] / self.result.scale, 2)
            obj.auto_size = False
            self._sync_props(("y", "auto_size"))
            self._update_prop_states()

    # ------------------------------------------------------------------ objects

    def select(self, obj: LabelObject | None) -> None:
        if obj is not self.selected:
            self.selected = obj
            self._build_props()
        self._draw_selection()

    def _placed_of(self, obj) -> Placed | None:
        if self.result is None or obj is None:
            return None
        return next((p for p in self.result.placed if p.obj is obj), None)

    def _next_x(self) -> float:
        if not self.result or not self.result.placed:
            return self.doc.margin_mm
        right = max(p.box[2] for p in self.result.placed) / self.result.scale
        return round(right + 1.5, 1)

    def insert(self, kind: str) -> None:
        doc = self.doc
        tape = doc.tape
        top = round(tape.band_top_mm, 2)
        band = round(tape.print_mm, 1)
        x = self._next_x()
        if kind == "text":
            obj = TextObject(x=x, y=top, font=fonts.REGISTRY.default_family())
        elif kind == "qrcode":
            obj = QRCodeObject(x=x, y=top, size=band)
        elif kind == "barcode":
            obj = BarcodeObject(x=x, y=top, height=band, show_text=band >= 6)
        elif kind == "image":
            obj = self._image_object_from_dialog(x, top, band)
            if obj is None:
                return
        elif kind == "frame":
            length = (self.result.length_mm if self.result else 40) - 2 * doc.margin_mm
            obj = FrameObject(x=doc.margin_mm, y=top, width=round(max(5.0, length), 1), height=band)
        else:
            obj = LineObject(x=x, y=round(top + band / 2 - 0.2, 2), length=20)
        doc.objects.append(obj)
        self.select(obj)
        self.changed()
        self.commit()

    def _read_image_dialog(self):
        name = filedialog.askopenfilename(parent=self.root, title="Bild laden", filetypes=IMAGE_TYPES,
                                          initialdir=self._initial_dir())
        if not name:
            return None
        try:
            img = Image.open(name)
            img.load()
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Bild kann nicht geladen werden:\n{exc}")
            return None
        img.thumbnail((MAX_IMAGE_PX, MAX_IMAGE_PX))
        if img.mode not in ("1", "L", "LA", "RGB", "RGBA"):
            img = img.convert("RGBA")
        buffer = io.BytesIO()
        img.save(buffer, "PNG")
        return base64.b64encode(buffer.getvalue()).decode("ascii"), Path(name).name, img.width / img.height

    def _image_object_from_dialog(self, x: float, y: float, height: float) -> ImageObject | None:
        loaded = self._read_image_dialog()
        if loaded is None:
            return None
        data, name, aspect = loaded
        return ImageObject(x=x, y=y, data=data, name=name, height=height, width=round(height * aspect, 1))

    def load_image_for_selected(self) -> None:
        obj = self.selected
        if not isinstance(obj, ImageObject):
            return
        loaded = self._read_image_dialog()
        if loaded is None:
            return
        obj.data, obj.name, aspect = loaded
        if obj.keep_aspect:
            obj.width = round(obj.height * aspect, 1)
        self._build_props()
        self.changed()
        self.commit()

    def delete_selected(self) -> None:
        index = _index_of(self.doc.objects, self.selected)
        if index is None:
            return
        del self.doc.objects[index]
        self.select(None)
        self.changed()
        self.commit()

    def duplicate(self) -> None:
        if self.selected is None:
            return
        copy = self.selected.copy()
        copy.x += 2
        if not (isinstance(copy, TextObject) and copy.auto_size):
            copy.y += 1
        self.doc.objects.append(copy)
        self.select(copy)
        self.changed()
        self.commit()

    def restack(self, direction: int) -> None:
        objects = self.doc.objects
        index = _index_of(objects, self.selected)
        if index is None:
            return
        target = max(0, min(len(objects) - 1, index + direction))
        objects.insert(target, objects.pop(index))
        self.changed()

    def center_vertically(self) -> None:
        obj, placed = self.selected, self._placed_of(self.selected)
        if obj is None or placed is None or (isinstance(obj, TextObject) and obj.auto_size):
            return
        top, bottom = self.result.band
        height = placed.box[3] - placed.box[1]
        obj.y = round((top + (bottom - top - height) / 2) / self.result.scale, 2)
        self._sync_props(("y",))
        self.changed()

    def nudge(self, dx: float, dy: float) -> str:
        obj = self.selected
        if obj is not None:
            obj.x = round(obj.x + dx, 2)
            if not (isinstance(obj, TextObject) and obj.auto_size):
                obj.y = round(obj.y + dy, 2)
            self._sync_props(("x", "y"))
            self.changed()
        return "break"

    # ------------------------------------------------------------------ canvas

    def _zoom(self) -> int:
        if self.zoom > 0:
            return self.zoom
        tape_px = round(self.doc.tape.width_mm * DPI / MM_PER_INCH)
        return max(1, min(10, round(260 / tape_px)))

    def set_zoom(self, zoom: int) -> None:
        self.zoom = 0 if zoom == 0 else max(1, min(12, zoom))
        self.redraw()

    def redraw(self) -> None:
        if self._render_job is None:
            self._render_job = self.root.after_idle(self._render_now)

    def _preview_colors(self):
        tape = self.status.tape_color_rgb if self.status else None
        ink = self.status.text_color_rgb if self.status else None
        return _rgb(tape or "#ffffff"), _rgb(ink or "#111111")

    def _render_now(self) -> None:
        self._render_job = None
        try:
            res = render(self.doc)
        except Exception as exc:
            self._set_message(f"Fehler bei der Darstellung: {exc}", COLOR_ERROR)
            return
        self.result = res
        z = self._zoom()
        self.lbl_zoom.configure(text=f"{z}×" + ("" if self.zoom else " auto"))

        tape_rgb, ink_rgb = self._preview_colors()
        mask = res.image
        img = Image.new("RGB", mask.size, tape_rgb)
        img.paste(ink_rgb, (0, 0), mask)
        shade = Image.new("L", mask.size, 0)
        draw = ImageDraw.Draw(shade)
        w, h = mask.size
        top, bottom = res.band
        if top > 0:
            draw.rectangle((0, 0, w - 1, top - 1), fill=110)
        if bottom < h:
            draw.rectangle((0, bottom, w - 1, h - 1), fill=110)
        m = res.margin_px
        if m > 0:
            draw.rectangle((0, top, m - 1, bottom - 1), fill=70)
            draw.rectangle((w - m, top, w - 1, bottom - 1), fill=70)
        img.paste(SHADE, (0, 0), shade)
        img = img.resize((w * z, h * z), Image.Resampling.NEAREST)
        self._photo = ImageTk.PhotoImage(img)

        c = self.canvas
        c.delete("all")
        ox = PAD
        oy = max(RULER_H + PAD, (c.winfo_height() - img.height) // 2)
        self._origin = (ox, oy)
        c.create_rectangle(ox + 4, oy + 4, ox + img.width + 4, oy + img.height + 4, fill="#5c626a", outline="")
        c.create_image(ox, oy, image=self._photo, anchor="nw")
        self._draw_ruler(res, z, img.width)
        self._draw_selection()
        c.configure(scrollregion=(0, 0, ox + img.width + PAD, oy + img.height + PAD))

        self.lbl_size.configure(text=f"{res.tape.label} × {res.length_mm:.1f} mm")
        self.lbl_warning.configure(text=" · ".join(dict.fromkeys(res.warnings)))
        self._show_effective_size()

    def _show_effective_size(self) -> None:
        """Show the computed size of an auto-sized text without touching the document."""
        sel, entry = self.selected, self._prop_vars.get("size")
        if isinstance(sel, TextObject) and sel.auto_size and entry:
            placed = self._placed_of(sel)
            if placed and placed.size_pt:
                self._syncing = True
                entry[1].set(_fmt(placed.size_pt))
                self._syncing = False

    def _draw_ruler(self, res: RenderResult, z: int, width: int) -> None:
        c = self.canvas
        ox, oy = self._origin
        y0, y1 = oy - RULER_H - 4, oy - 4
        c.create_rectangle(ox, y0, ox + width, y1, fill="#eef0f2", outline="#c5c9ce")
        px_per_mm = res.scale * z
        step = 1 if px_per_mm >= 5 else 5
        for mm in range(0, int(res.length_mm) + 1, step):
            x = ox + mm * px_per_mm
            tick = 10 if mm % 10 == 0 else 6 if mm % 5 == 0 else 3
            c.create_line(x, y1 - tick, x, y1, fill="#555")
            if mm % 10 == 0:
                c.create_text(x + 3, y0 + 1, text=str(mm), anchor="nw", fill="#333", font="TkSmallCaptionFont")

    def _to_screen(self, box) -> tuple[float, float, float, float]:
        z = self._zoom()
        ox, oy = self._origin
        return ox + box[0] * z, oy + box[1] * z, ox + box[2] * z, oy + box[3] * z

    def _draw_selection(self) -> None:
        c = self.canvas
        c.delete("sel")
        placed = self._placed_of(self.selected)
        if placed is None:
            return
        x0, y0, x1, y1 = self._to_screen(placed.box)
        c.create_rectangle(x0 - 1, y0 - 1, x1, y1, outline=ACCENT, dash=(4, 2), width=1, tags="sel")
        r = HANDLE // 2
        c.create_rectangle(x1 - r, y1 - r, x1 + r, y1 + r, fill="white", outline=ACCENT, tags="sel")

    def _label_xy(self, event) -> tuple[float, float]:
        z = self._zoom()
        ox, oy = self._origin
        return (self.canvas.canvasx(event.x) - ox) / z, (self.canvas.canvasy(event.y) - oy) / z

    def _hit(self, px: float, py: float) -> LabelObject | None:
        """Smallest object under the cursor; empty frames only react to their outline."""
        z = self._zoom()
        tolerance = 3 / z
        best = None
        for placed in reversed(self.result.placed if self.result else []):
            x0, y0, x1, y1 = placed.box
            if not (x0 - tolerance <= px <= x1 + tolerance and y0 - tolerance <= py <= y1 + tolerance):
                continue
            obj = placed.obj
            if isinstance(obj, FrameObject) and not obj.fill:
                edge = obj.thickness * self.result.scale + 4 / z
                if min(px - x0, x1 - px, py - y0, y1 - py) > edge:
                    continue
            area = (x1 - x0) * (y1 - y0)
            if best is None or area < best[0]:
                best = (area, obj)
        return best[1] if best else None

    def _on_press(self, event) -> None:
        self.canvas.focus_set()
        if self.result is None:
            return
        px, py = self._label_xy(event)
        placed = self._placed_of(self.selected)
        grip = (HANDLE / 2 + 2) / self._zoom()
        if placed and abs(px - placed.box[2]) <= grip and abs(py - placed.box[3]) <= grip:
            obj = self.selected
            if isinstance(obj, TextObject):
                self._freeze_auto_text(obj)
            size = (max(1, placed.box[2] - placed.box[0]), max(1, placed.box[3] - placed.box[1]))
            self._drag = {"mode": "resize", "obj": obj, "start": (px, py), "orig": obj.copy(), "size": size,
                          "moved": False}
            return
        hit = self._hit(px, py)
        self.select(hit)
        if hit is not None:
            self._drag = {"mode": "move", "obj": hit, "start": (px, py), "orig": (hit.x, hit.y), "moved": False}

    def _on_motion(self, event) -> None:
        drag = self._drag
        if not drag or self.result is None:
            return
        px, py = self._label_xy(event)
        dx, dy = px - drag["start"][0], py - drag["start"][1]
        if not drag["moved"] and abs(dx) * self._zoom() < 3 and abs(dy) * self._zoom() < 3:
            return
        drag["moved"] = True
        obj, scale = drag["obj"], self.result.scale
        if drag["mode"] == "move":
            obj.x = round(drag["orig"][0] + dx / scale, 1)
            if not (isinstance(obj, TextObject) and obj.auto_size):
                obj.y = round(drag["orig"][1] + dy / scale, 1)
            self._sync_props(("x", "y"))
        else:
            w0, h0 = drag["size"]
            fx, fy = max(1.0, w0 + dx) / w0, max(1.0, h0 + dy) / h0
            if obj.rotation % 180:
                fx, fy = fy, fx
            obj.resize(drag["orig"], fx, fy)
            self._sync_props()
        self.redraw()

    def _on_release(self, _event) -> None:
        drag, self._drag = self._drag, None
        if drag and drag["moved"]:
            self.changed()
            self.commit()

    def _on_double(self, event) -> None:
        if self.selected is None:
            return
        for attr in ("text", "data"):
            widget = self._text_widgets.get(attr)
            if widget is not None:
                widget.focus_set()
                widget.tag_add("sel", "1.0", "end-1c")
                return

    def _on_context(self, event) -> None:
        if self.result is None:
            return
        hit = self._hit(*self._label_xy(event))
        if hit is not None:
            self.select(hit)
            self.context_menu.tk_popup(event.x_root, event.y_root)

    def _on_wheel(self, event) -> str:
        up = event.num == 4 or getattr(event, "delta", 0) > 0
        if event.state & 0x0004:  # Ctrl: zoom
            self.set_zoom(self._zoom() + (1 if up else -1))
        elif event.state & 0x0001:  # Shift: vertical
            self.canvas.yview_scroll(-1 if up else 1, "units")
        else:
            self.canvas.xview_scroll(-3 if up else 3, "units")
        return "break"

    # ------------------------------------------------------------------ printer

    def _set_message(self, text: str, color: str = COLOR_INFO) -> None:
        self.lbl_message.configure(text=text, foreground=color)

    def _printer_changed(self) -> None:
        target = self.v_printer.get().strip()
        if target != self.cfg.get("printer", ""):
            self.cfg["printer"] = target
            config.save(self.cfg)
            self.status = None
            self.refresh_status(manual=True)

    def _startup_printer(self) -> None:
        if self.v_printer.get().strip():
            self._periodic_status()
        else:
            self.discover(silent=True, then=self._periodic_status)

    def _periodic_status(self) -> None:
        self.refresh_status()
        self.root.after(STATUS_INTERVAL_MS, self._periodic_status)

    def refresh_status(self, manual: bool = False) -> None:
        target = self.v_printer.get().strip()
        if not target:
            self._show_printer_text("Kein Drucker eingestellt – Drucker einschalten und „Suchen…“ klicken "
                                    "oder Hostname/IP eintragen", COLOR_WARN)
            return
        if self._status_pending or self._busy:
            return
        self._status_pending = True
        if manual:
            self._show_printer_text(f"Frage {target} ab …", COLOR_INFO)

        def done(status, error):
            self._status_pending = False
            if error is not None:
                had_status = self.status is not None
                self.status = None
                self._show_printer_text(str(error), COLOR_ERROR)
                self._update_tape_warning()
                if had_status:
                    self.redraw()
                return
            self._apply_status(status)

        self.run_bg(lambda: open_printer(target).status(), done)

    def _show_printer_text(self, text: str, color: str) -> None:
        self.lbl_status.configure(text=text, foreground=color)
        self.lbl_printer.configure(text=text if len(text) < 70 else text[:67] + "…", foreground=color)

    def _apply_status(self, status: PrinterStatus) -> None:
        old = self.status
        self.status = status
        self._show_printer_text(f"{status.model}: {status.summary()}", COLOR_ERROR if status.errors else COLOR_OK)
        if not self._tape_checked and status.tape:
            self._tape_checked = True
            if self._is_pristine() and status.tape.width_mm != self.doc.tape_mm:
                self.doc.tape_mm = status.tape.width_mm
                self._load_state()
                self.select(self.doc.objects[0] if self.doc.objects else None)
        self._update_tape_warning()
        if old is None or (old.tape_color, old.text_color) != (status.tape_color, status.text_color):
            self.redraw()

    def _update_tape_warning(self) -> None:
        tape = self.status.tape if self.status else None
        if tape and tape.code != self.doc.tape.code:
            self.btn_adopt.configure(text=f"Eingelegtes Band ({tape.label}) übernehmen")
            self.btn_adopt.pack(side="left", padx=(8, 0), after=self.lbl_printer)
        else:
            self.btn_adopt.pack_forget()

    def adopt_tape(self) -> None:
        if self.status and self.status.tape:
            self.doc.tape_mm = self.status.tape.width_mm
            self._sync_label_panel()
            self._update_tape_warning()
            self.changed()

    def discover(self, silent: bool = False, then=None) -> None:
        if not silent:
            self._set_message("Suche Brother-Drucker im Netzwerk …")

        def done(found, error):
            self._set_message("")
            found = found or []
            label_printers = [p for p in found if p.model.upper().startswith(("PT", "QL"))]
            if error is not None and not silent:
                messagebox.showerror(APP_NAME, f"Suche fehlgeschlagen:\n{error}")
            elif len(label_printers) == 1:
                self._use_printer(label_printers[0].address)
            elif found and not silent:
                self._choose_printer(found)
            elif not silent:
                messagebox.showinfo(APP_NAME, "Kein Brother-Drucker gefunden.\n"
                                              "Bitte Hostname oder IP-Adresse von Hand eintragen.")
            if then:
                then()

        self.run_bg(lambda: discover_printers(2.0), done)

    def _use_printer(self, address: str) -> None:
        self.v_printer.set(address)
        self._printer_changed()

    def _choose_printer(self, printers) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Drucker auswählen")
        dialog.transient(self.root)
        dialog.grab_set()
        ttk.Label(dialog, text="Gefundene Brother-Drucker:", padding=(10, 10, 10, 4)).pack(anchor="w")
        listbox = tk.Listbox(dialog, width=56, height=min(10, len(printers)), activestyle="none")
        for p in printers:
            listbox.insert("end", f"{p.model:14}  {p.address}  ({p.ip})")
        listbox.selection_set(0)
        listbox.pack(fill="both", expand=True, padx=10)

        def accept(_event=None):
            selection = listbox.curselection()
            if selection:
                self._use_printer(printers[selection[0]].address)
            dialog.destroy()

        buttons = ttk.Frame(dialog, padding=10)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Abbrechen", command=dialog.destroy).pack(side="right")
        ttk.Button(buttons, text="Übernehmen", command=accept).pack(side="right", padx=6)
        listbox.bind("<Double-Button-1>", accept)
        dialog.bind("<Return>", accept)
        dialog.bind("<Escape>", lambda e: dialog.destroy())

    def print_label(self) -> None:
        if self._busy:
            return
        self._flush_commit()
        target = self.v_printer.get().strip()
        if not target:
            if messagebox.askyesno(APP_NAME, "Es ist kein Drucker eingestellt. Jetzt im Netzwerk suchen?"):
                self.discover()
            return
        doc = self.doc
        tape = self.status.tape if self.status else None
        if tape and tape.code != doc.tape.code and not messagebox.askyesno(
                APP_NAME, f"Im Drucker ist {tape.label}-Band eingelegt, das Etikett ist für {doc.tape.label} "
                          "angelegt.\n\nTrotzdem drucken?"):
            return
        try:
            pages = print_pages(doc)
            job = build_job(pages, doc.tape, doc.print_options())
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Etikett kann nicht erzeugt werden:\n{exc}")
            return
        self._busy = True
        self._set_message(f"Sende {len(pages)} Etikett(en) an {target} …")

        def work():
            printer = open_printer(target)
            printer.send(job)
            if not isinstance(printer, NetworkPrinter):
                return None
            try:
                return wait_for_completion(printer)
            except PrinterError:  # job was sent, only the follow-up status failed
                return None

        def done(status, error):
            self._busy = False
            if error is not None:
                self._set_message("Druck fehlgeschlagen", COLOR_ERROR)
                messagebox.showerror(APP_NAME, f"Druck fehlgeschlagen:\n{error}")
                return
            if status is not None:
                self._apply_status(status)
            if status is not None and status.errors:
                self._set_message("Drucker meldet Fehler", COLOR_ERROR)
                messagebox.showerror(APP_NAME, "Der Drucker meldet:\n" + "\n".join(status.errors))
            else:
                self._set_message(f"{len(pages)} Etikett(en) gedruckt", COLOR_OK)

        self.run_bg(work, done)

    def show_usage(self) -> None:
        messagebox.showinfo(APP_NAME, (
            "• Objekte über die Werkzeugleiste oder „Einfügen“ hinzufügen.\n"
            "• Objekt anklicken und mit der Maus verschieben; das weiße Quadrat unten rechts ändert die Größe.\n"
            "• Pfeiltasten verschieben um 0,5 mm (mit Umschalt um 0,1 mm), Entf löscht.\n"
            "• Doppelklick springt in das Textfeld, Rechtsklick öffnet das Kontextmenü.\n"
            "• Mausrad scrollt, Strg+Mausrad zoomt.\n"
            "• Grau schattierte Bereiche werden nicht gedruckt (Bandrand und Ränder).\n"
            "• Die Vorschau zeigt die Farben des eingelegten Bandes."))


def run() -> int:
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0
