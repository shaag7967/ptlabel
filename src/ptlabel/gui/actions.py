"""All menu and toolbar actions with their texts, icons and shortcuts."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QWidget

from ..i18n import tr
from .icons import icon

S = QKeySequence.StandardKey


@dataclass(frozen=True)
class ActionSpec:
    key: str
    text: str
    icon: str | None = None
    shortcut: object = None  # StandardKey, string or list of both
    tip: str = ""
    checkable: bool = False


INSERT_KINDS = [("text", tr("Text"), "type"), ("qrcode", tr("QR code"), "qr-code"),
                ("barcode", tr("Barcode"), "barcode"), ("image", tr("Image…"), "image"),
                ("frame", tr("Frame"), "square"), ("line", tr("Line"), "minus")]

SPECS = [
    ActionSpec("new", tr("New"), "file-plus", S.New),
    ActionSpec("open", tr("Open…"), "folder-open", S.Open),
    ActionSpec("save", tr("Save"), "save", S.Save),
    ActionSpec("save_as", tr("Save as…"), "save-all", "Ctrl+Shift+S"),
    ActionSpec("export", tr("Export as PNG…"), "image-down"),
    ActionSpec("quit", tr("Quit"), "log-out", S.Quit),
    ActionSpec("undo", tr("Undo"), "undo-2", S.Undo),
    ActionSpec("redo", tr("Redo"), "redo-2", ["Ctrl+Y", "Ctrl+Shift+Z"]),
    ActionSpec("duplicate", tr("Duplicate"), "copy", "Ctrl+D"),
    ActionSpec("delete", tr("Delete"), "trash-2", S.Delete),
    ActionSpec("front", tr("Bring forward"), "bring-to-front", "Ctrl+]"),
    ActionSpec("back", tr("Send backward"), "send-to-back", "Ctrl+["),
    ActionSpec("center", tr("Center vertically"), "align-vertical-justify-center"),
    *(ActionSpec(f"insert_{kind}", text, name, tip=tr("Insert {object}").format(object=text.rstrip("…")))
      for kind, text, name in INSERT_KINDS),
    ActionSpec("zoom_in", tr("Zoom in"), "zoom-in", ["Ctrl++", "Ctrl+="]),
    ActionSpec("zoom_out", tr("Zoom out"), "zoom-out", "Ctrl+-"),
    ActionSpec("zoom_auto", tr("Automatic zoom"), "scan", "Ctrl+0"),
    ActionSpec("snap", tr("Snap to guides"), "magnet", checkable=True,
               tip=tr("Align objects with the tape center, the margins and other objects while dragging (Alt: off)")),
    ActionSpec("reset_layout", tr("Reset panel layout")),
    ActionSpec("print", tr("Print"), "printer", S.Print),
    ActionSpec("status", tr("Query status"), "refresh-cw"),
    ActionSpec("discover", tr("Find printers…"), "radar"),
    ActionSpec("add_fonts", tr("Add font files…"), "file-type"),
    ActionSpec("web_fonts", tr("Download Google Fonts…"), "download"),
    ActionSpec("font_folder", tr("Open font folder"), "folder"),
    ActionSpec("placeholders", tr("Placeholders…"), "braces"),
    ActionSpec("usage", tr("Usage…"), "book-open"),
    ActionSpec("about", tr("About…"), "info"),
]


class Actions:
    """Creates the actions; access them by key, e.g. ``actions["save"]``."""

    def __init__(self, parent: QWidget):
        self._actions: dict[str, QAction] = {}
        for spec in SPECS:
            action = QAction(spec.text, parent)
            if spec.icon:
                action.setIcon(icon(spec.icon))
            if spec.shortcut is not None:
                shortcuts = spec.shortcut if isinstance(spec.shortcut, list) else [spec.shortcut]
                action.setShortcuts([QKeySequence(s) for s in shortcuts])
            tip = spec.tip or spec.text.rstrip("…")
            if action.shortcut().toString():
                tip += f"  ({action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)})"
            action.setToolTip(tip)
            action.setStatusTip(spec.tip)
            action.setCheckable(spec.checkable)
            self._actions[spec.key] = action

    def __getitem__(self, key: str) -> QAction:
        return self._actions[key]

    def connect(self, slots: dict) -> None:
        for key, slot in slots.items():
            self._actions[key].triggered.connect(lambda checked=False, s=slot: s())
