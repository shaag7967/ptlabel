"""Font previews in drop-down lists and the Google Fonts download dialog."""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QPushButton, QStyledItemDelegate,
                               QStyleOptionViewItem, QVBoxLayout)

from .. import fonts, webfonts
from ..i18n import tr
from .qtutil import BackgroundRunner, set_tone

PREVIEW_SAMPLE = "AaBbCc 0123 ÄÖÜ €"


class FontPreviews:
    """Maps font family names of the registry to Qt families, loading font files on demand."""

    def __init__(self):
        self._cache: dict[str, str | None] = {}
        self._known: dict[str, str] | None = None

    def clear(self) -> None:
        self._cache.clear()
        self._known = None

    def qt_family(self, family: str) -> str | None:
        """Qt family that shows ``family``; None for unknown, symbol and non-Latin fonts."""
        if family in self._cache:
            return self._cache[family]
        if self._known is None:
            self._known = {name.casefold(): name for name in QFontDatabase.families()}
        name = self._known.get(family.casefold())
        if name is None:
            face = fonts.REGISTRY.resolve(family, False, False)
            if face is not None and face.family.casefold() == family.casefold():
                name = self.load_file(face.path, family)
        if name is not None:
            systems = QFontDatabase.writingSystems(name)
            WS = QFontDatabase.WritingSystem
            if WS.Latin not in systems or WS.Symbol in systems:
                name = None  # e.g. Dingbats: its name would only show pictograms
        self._cache[family] = name
        return name

    @staticmethod
    def load_file(path: str, family: str = "") -> str | None:
        font_id = QFontDatabase.addApplicationFont(path)
        families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
        return next((f for f in families if f.casefold() == family.casefold()), families[0] if families else None)


PREVIEWS = FontPreviews()


class FontPreviewDelegate(QStyledItemDelegate):
    """Draws each family name in its own font."""

    def initStyleOption(self, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        super().initStyleOption(option, index)
        name = PREVIEWS.qt_family(str(index.data() or ""))
        if name:
            font = QFont(option.font)
            font.setFamily(name)
            font.setPointSizeF(option.font.pointSizeF() * 1.2)
            option.font = font

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        size = super().sizeHint(option, index)
        return QSize(size.width(), max(size.height(), round(option.fontMetrics.height() * 1.9)))


def add_font_previews(combo: QComboBox) -> None:
    delegate = FontPreviewDelegate(combo)
    combo.setItemDelegate(delegate)
    combo.view().setUniformItemSizes(True)  # one size hint for all rows keeps long lists fast
    combo.setMaxVisibleItems(16)
    completer = combo.completer()
    if completer is not None:
        completer.popup().setItemDelegate(FontPreviewDelegate(completer.popup()))


class WebFontDialog(QDialog):
    """Search Google Fonts, preview a family and install it into the user font folder."""

    installed = Signal(list)  # family names

    CATEGORIES = [("", tr("All categories")), ("sans-serif", tr("Sans serif")), ("serif", tr("Serif")),
                  ("display", tr("Display")), ("handwriting", tr("Handwriting")), ("monospace", tr("Monospace"))]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Download Google Fonts"))
        self.resize(560, 560)
        self._fonts: list[webfonts.WebFont] = []
        self._bg = BackgroundRunner(self)
        self._preview_for = ""

        layout = QVBoxLayout(self)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Search…"))
        self.search.setClearButtonEnabled(True)
        self.category = QComboBox()
        for value, label in self.CATEGORIES:
            self.category.addItem(label, value)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.category)
        layout.addLayout(filters)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setUniformItemSizes(True)
        layout.addWidget(self.list, 1)

        self.preview = QLabel()
        self.preview.setMinimumHeight(64)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet("QLabel { background: white; color: black; border-radius: 8px; }")
        layout.addWidget(self.preview)
        self.info = QLabel()
        self.info.setWordWrap(True)
        layout.addWidget(self.info)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.install_button = QPushButton(tr("Install"))
        self.install_button.setEnabled(False)
        buttons.addButton(self.install_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._filter_timer = QTimer(self, singleShot=True, interval=150)
        self._filter_timer.timeout.connect(self._fill_list)
        self.search.textChanged.connect(self._filter_timer.start)
        self.category.currentIndexChanged.connect(self._fill_list)
        self.list.currentItemChanged.connect(self._on_current)
        self.list.itemDoubleClicked.connect(self._install)
        self.install_button.clicked.connect(self._install)

        self._show_info(tr("Loading the font list …"))
        self._bg.run(webfonts.list_fonts, self._on_list)

    def _show_info(self, text: str, tone: str = "info") -> None:
        self.info.setText(text)
        set_tone(self.info, tone)

    def _on_list(self, result, error) -> None:
        if error is not None:
            self._show_info(tr("The font list cannot be loaded:\n{error}").format(error=error), "error")
            return
        self._fonts = result
        self._show_info(tr("Fonts are installed for PT-Label only (regular and bold, upright and italic)."))
        self._fill_list()
        self.search.setFocus()

    def _fill_list(self) -> None:
        query = self.search.text().strip().casefold()
        category = self.category.currentData()
        installed = {name.casefold() for name in fonts.REGISTRY.families()}
        self.list.clear()
        for font in self._fonts:
            if query and query not in font.family.casefold():
                continue
            if category and font.category != category:
                continue
            label = font.family + ("  ✓" if font.family.casefold() in installed else "")
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, font)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)

    def _current_font(self) -> webfonts.WebFont | None:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _on_current(self, *_) -> None:
        font = self._current_font()
        self.install_button.setEnabled(font is not None)
        if font is None:
            self.preview.clear()
            return
        self._preview_for = font.id
        self.preview.setFont(self.font())
        self.preview.setText(tr("Loading preview …"))
        self._bg.run(lambda: webfonts.download_regular(font), lambda path, error: self._show_preview(font, path, error))

    def _show_preview(self, font: webfonts.WebFont, path, error) -> None:
        if font.id != self._preview_for:
            return  # the selection changed meanwhile
        name = None if error is not None else FontPreviews.load_file(str(path), font.family)
        if name is None:
            self.preview.setText(tr("No preview available"))
            return
        qfont = QFont(name)
        qfont.setPointSizeF(self.font().pointSizeF() * 1.8)
        self.preview.setFont(qfont)
        self.preview.setText(f"{font.family}\n{PREVIEW_SAMPLE}")

    def _install(self, *_) -> None:
        font = self._current_font()
        if font is None:
            return
        self.install_button.setEnabled(False)
        self._show_info(tr("Installing {family} …").format(family=font.family))

        def done(families, error):
            self.install_button.setEnabled(True)
            if error is not None:
                self._show_info(tr("Installation failed:\n{error}").format(error=error), "error")
                return
            self._show_info(tr("Installed: {families}").format(families=", ".join(families)))
            PREVIEWS.clear()
            row = self.list.currentRow()
            self._fill_list()
            self.list.setCurrentRow(row)
            self.installed.emit(families)

        self._bg.run(lambda: webfonts.install(font), done)
