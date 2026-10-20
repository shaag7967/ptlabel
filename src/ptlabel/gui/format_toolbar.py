"""Toolbar with font, size, style and alignment of the selected text."""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import QToolBar

from .. import fonts
from ..i18n import tr
from ..model import TextObject
from .document import DocumentController
from .icons import icon
from .widgets import FontComboBox, NumberSpin

# alignment on the label: (text alignment, position on the label, icon, tooltip)
ALIGNMENTS = [("left", "free", "text-align-start", tr("Align left (free position)")),
              ("center", "center", "text-align-center", tr("Center on the label")),
              ("right", "right", "text-align-end", tr("Align at the right margin"))]


POSITION_TO_ALIGN = {position: align for align, position, *_ in ALIGNMENTS}


class FormatToolBar(QToolBar):
    def __init__(self, document: DocumentController):
        super().__init__(tr("Format"))
        self.setObjectName("format_toolbar")
        self.document = document
        self.font_box = FontComboBox()
        self.font_box.setToolTip(tr("Font"))
        self.size = NumberSpin(3, 300, 1, suffix=" pt")
        self.size.setToolTip(tr("Font size; changing it switches the automatic size off"))
        self.auto_size = self._toggle("a-large-small", tr("Automatic size (fill tape height)"), "auto_size")
        self.addWidget(self.font_box)
        self.addWidget(self.size)
        self.addAction(self.auto_size)
        self.addSeparator()
        self.bold = self._toggle("bold", tr("Bold"), "bold", QKeySequence.StandardKey.Bold)
        self.italic = self._toggle("italic", tr("Italic"), "italic", QKeySequence.StandardKey.Italic)
        self.underline = self._toggle("underline", tr("Underline"), "underline", QKeySequence.StandardKey.Underline)
        for action in (self.bold, self.italic, self.underline):
            self.addAction(action)
        self.addSeparator()
        group = QActionGroup(self)
        self.align: dict[str, QAction] = {}
        for value, position, name, text in ALIGNMENTS:
            action = QAction(icon(name), text, self)
            action.setCheckable(True)
            action.triggered.connect(lambda _=False, v=value, p=position: self._align(v, p))
            group.addAction(action)
            self.addAction(action)
            self.align[value] = action

        self.font_box.currentTextChanged.connect(self._font_changed)
        self.size.valueChanged.connect(lambda v: self._set("size", v))
        document.selection_changed.connect(self.refresh)
        document.changed.connect(self.refresh)
        document.reset.connect(self.refresh)
        document.rendered.connect(self.refresh)
        self.refresh()

    def _toggle(self, name: str, text: str, attr: str, shortcut=None) -> QAction:
        action = QAction(icon(name), text, self)
        action.setCheckable(True)
        if shortcut is not None:
            action.setShortcut(QKeySequence(shortcut))
        action.toggled.connect(lambda on: self._set(attr, on))
        return action

    def _text(self) -> TextObject | None:
        obj = self.document.selected
        return obj if isinstance(obj, TextObject) else None

    def _set(self, attr: str, value) -> None:
        obj = self._text()
        if obj is not None and getattr(obj, attr) != value:
            self.document.set_property(obj, attr, value)

    def _align(self, align: str, position: str) -> None:
        """Align the lines and place the whole text on the label."""
        obj = self._text()
        if obj is not None and (obj.align, obj.h_align) != (align, position):
            obj.align = align
            self.document.set_property(obj, "h_align", position)
            self.document.commit()

    def _font_changed(self, name: str) -> None:
        family = fonts.REGISTRY.find_family(name)
        if family:
            self._set("font", family)

    def refresh(self) -> None:
        obj = self._text()
        for widget in (self.font_box, self.size):
            widget.setEnabled(obj is not None)
        actions = [self.auto_size, self.bold, self.italic, self.underline, *self.align.values()]
        for action in actions:
            action.setEnabled(obj is not None)
        if obj is None:
            return
        self.font_box.set_family(fonts.REGISTRY.find_family(obj.font or "") or fonts.REGISTRY.default_family())
        placed = self.document.placed_of(obj)
        size = placed.size_pt if obj.auto_size and placed and placed.size_pt else obj.size
        self.size.set_quietly(round(size, 1))
        for action, on in ((self.auto_size, obj.auto_size), (self.bold, obj.bold), (self.italic, obj.italic),
                           (self.underline, obj.underline), *((a, POSITION_TO_ALIGN.get(obj.h_align) == v) for v, a in self.align.items())):
            if action.isChecked() != on:
                with QSignalBlocker(action):
                    action.setChecked(on)
