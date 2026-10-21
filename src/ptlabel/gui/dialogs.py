"""Message boxes and small dialogs."""

from __future__ import annotations

import base64
import io
from pathlib import Path

from PIL import Image
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QLabel, QListWidget, QMessageBox,
                               QVBoxLayout, QWidget)

from .. import __version__
from ..i18n import tr
from ..model import PLACEHOLDER_HELP
from ..printer import PrinterInfo
from .qtutil import APP_NAME, MAX_IMAGE_PX

LABEL_FILTER = tr("PT-Label label") + " (*.ptlabel);;" + tr("All files") + " (*)"
IMAGE_FILTER = tr("Images") + " (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp);;" + tr("All files") + " (*)"
CSV_FILTER = tr("Tables") + " (*.csv *.txt *.tsv);;" + tr("All files") + " (*)"
FONT_FILTER = tr("Fonts") + " (*.ttf *.otf *.ttc *.otc);;" + tr("All files") + " (*)"
USAGE = tr(
    "• Add objects with the toolbar or the “Insert” menu.\n"
    "• Click an object and drag it with the mouse; the white square at the bottom right changes its size.\n"
    "• Arrow keys move by 0.5 mm (0.1 mm with Shift), Del deletes.\n"
    "• Double-click jumps to the text field, right-click opens the context menu.\n"
    "• The mouse wheel scrolls, Ctrl+wheel zooms.\n"
    "• Gray shaded areas are not printed (tape edges and margins).\n"
    "• The preview shows the colors of the loaded tape.")
SNAP_HINT = tr("While dragging, objects snap to the tape center, the margins and other objects. "
               "Hold Alt to move freely.")


def error(parent: QWidget, text: str) -> None:
    QMessageBox.critical(parent, APP_NAME, text)


def info(parent: QWidget, text: str) -> None:
    QMessageBox.information(parent, APP_NAME, text)


def confirm(parent: QWidget, text: str) -> bool:
    return QMessageBox.question(parent, APP_NAME, text) == QMessageBox.StandardButton.Yes


def ask_save_changes(parent: QWidget) -> str:
    """'save', 'discard' or 'cancel'."""
    B = QMessageBox.StandardButton
    answer = QMessageBox.question(parent, APP_NAME, tr("The label has been modified. Save changes?"),
                                  B.Save | B.Discard | B.Cancel, B.Save)
    return {B.Save: "save", B.Discard: "discard"}.get(answer, "cancel")


def show_usage(parent: QWidget) -> None:
    QMessageBox.information(parent, tr("Usage"), USAGE + "\n• " + SNAP_HINT)


def show_placeholders(parent: QWidget) -> None:
    QMessageBox.information(parent, tr("Placeholders"),
                            tr("Usable in texts, QR codes and barcodes:") + "\n\n" + PLACEHOLDER_HELP)


def show_about(parent: QWidget) -> None:
    QMessageBox.about(parent, APP_NAME, f"<h3>{APP_NAME} {__version__}</h3>"
                      f"<p>{tr('Label editor for the Brother PT-P750W')}</p>"
                      f"<p>{tr('Icons: Lucide (ISC license). Bundled fonts: SIL Open Font License.')}</p>")


def open_label_name(parent: QWidget, start_dir: str) -> str:
    name, _ = QFileDialog.getOpenFileName(parent, tr("Open label"), start_dir, LABEL_FILTER)
    return name


def save_name(parent: QWidget, title: str, start_dir: str, file_filter: str, suffix: str) -> Path | None:
    name, _ = QFileDialog.getSaveFileName(parent, title, start_dir, file_filter)
    if not name:
        return None
    path = Path(name)
    return path if path.suffix else path.with_suffix(suffix)


def read_image(parent: QWidget, start_dir: str) -> tuple[str, str, float] | None:
    """Ask for an image; returns (base64 PNG, file name, aspect ratio) or None."""
    name, _ = QFileDialog.getOpenFileName(parent, tr("Load image"), start_dir, IMAGE_FILTER)
    if not name:
        return None
    try:
        img = Image.open(name)
        img.load()
    except OSError as exc:
        error(parent, tr("The image cannot be loaded:\n{error}").format(error=exc))
        return None
    img.thumbnail((MAX_IMAGE_PX, MAX_IMAGE_PX))
    if img.mode not in ("1", "L", "LA", "RGB", "RGBA"):
        img = img.convert("RGBA")
    buffer = io.BytesIO()
    img.save(buffer, "PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii"), Path(name).name, img.width / img.height


def choose_printer(parent: QWidget, printers: list[PrinterInfo]) -> str | None:
    """Let the user pick one of several printers; returns its address."""
    dialog = QDialog(parent)
    dialog.setWindowTitle(tr("Select printer"))
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel(tr("Brother printers found:")))
    listbox = QListWidget()
    listbox.addItems([f"{p.model}  {p.address}  ({p.ip})" for p in printers])
    listbox.setCurrentRow(0)
    listbox.itemDoubleClicked.connect(dialog.accept)
    layout.addWidget(listbox)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("Use"))
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    dialog.resize(480, 260)
    if dialog.exec() == QDialog.DialogCode.Accepted and listbox.currentRow() >= 0:
        return printers[listbox.currentRow()].address
    return None
