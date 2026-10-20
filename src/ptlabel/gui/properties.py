"""Property editor for the selected object, generated from the object's ``Prop`` list."""

from __future__ import annotations

from PySide6.QtCore import QObject, QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QPushButton, QVBoxLayout, QWidget)

from .. import barcodes, fonts
from ..i18n import tr
from ..model import BarcodeObject, ImageObject, LabelObject, Prop, TextObject
from .document import DocumentController
from .icons import icon
from .qtutil import set_tone
from .widgets import FontComboBox, NumberSpin, section_label

POSITION_ATTRS = ("h_align", "x", "y", "rotation")
KIND_ICONS = {"text": "type", "qrcode": "qr-code", "barcode": "barcode", "image": "image", "frame": "square",
              "line": "minus"}


class PropField(QObject):
    """Editor widget for one ``Prop`` of an object."""

    changed = Signal()

    def __init__(self, prop: Prop):
        super().__init__()
        self.prop = prop
        kind = prop.kind
        if kind == "bool":
            self.widget = QCheckBox(prop.label)
            self.widget.toggled.connect(self.changed)
        elif kind in ("float", "int"):
            lo, hi, step = prop.options
            self.widget = NumberSpin(lo, hi, step, 0 if kind == "int" else 2)
            self.widget.valueChanged.connect(self.changed)
        elif kind == "choice":
            self.widget = QComboBox()
            for data, label in prop.options:
                self.widget.addItem(label, data)
            self.widget.currentIndexChanged.connect(self.changed)
        elif kind == "font":
            self.widget = FontComboBox()
            self.widget.currentTextChanged.connect(self.changed)
        elif kind == "multiline":
            self.widget = QPlainTextEdit()
            self.widget.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
            self.widget.setTabChangesFocus(True)
            self.widget.setFixedHeight(self.widget.fontMetrics().lineSpacing() * 3 + 14)
            self.widget.textChanged.connect(self.changed)
        else:
            self.widget = QLineEdit()
            self.widget.textChanged.connect(self.changed)

    def value(self):
        w, kind = self.widget, self.prop.kind
        if kind == "bool":
            return w.isChecked()
        if kind == "float":
            return w.value()
        if kind == "int":
            return int(round(w.value()))
        if kind == "choice":
            return w.currentData()
        if kind == "font":
            return fonts.REGISTRY.find_family(w.currentText())  # None while a name is being typed
        if kind == "multiline":
            return w.toPlainText()
        return w.text()

    def show_value(self, value) -> None:
        """Display ``value`` without emitting ``changed``; leaves a field alone while it is being edited."""
        w, kind = self.widget, self.prop.kind
        if kind != "bool" and w.hasFocus() and kind not in ("choice",):
            return
        with QSignalBlocker(w):
            if kind == "bool":
                w.setChecked(bool(value))
            elif kind in ("float", "int"):
                if w.value() != float(value):
                    w.setValue(float(value))
            elif kind == "choice":
                index = w.findData(value)
                if index >= 0:
                    w.setCurrentIndex(index)
            elif kind == "font":
                w.set_family(fonts.REGISTRY.find_family(value or "") or fonts.REGISTRY.default_family())
            elif kind == "multiline":
                if w.toPlainText() != value:
                    w.setPlainText(value)
            elif w.text() != str(value):
                w.setText(str(value))


class PropertyEditor(QWidget):
    """Fields of the selected object, grouped into its own settings and its position."""

    image_requested = Signal()

    def __init__(self, document: DocumentController):
        super().__init__()
        self.document = document
        self._fields: dict[str, PropField] = {}
        self._obj: LabelObject | None = None
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(10, 8, 10, 10)
        self._content: QWidget | None = None
        document.selection_changed.connect(self.rebuild)
        document.reset.connect(self.rebuild)
        document.changed.connect(self.refresh)
        document.rendered.connect(self._show_effective_size)
        self.rebuild()

    # ------------------------------------------------------------------ building

    def rebuild(self) -> None:
        if self._content is not None:
            self._layout.removeWidget(self._content)
            self._content.hide()
            self._content.deleteLater()
        self._fields = {}
        self._obj = self.document.selected
        self._content = QWidget()
        column = QVBoxLayout(self._content)
        column.setContentsMargins(0, 0, 0, 0)
        self._layout.addWidget(self._content)
        obj = self._obj
        if obj is None:
            hint = QLabel(tr("No object selected.\nClick an object or add a new one\nwith “Insert”."))
            hint.setWordWrap(True)
            set_tone(hint, "info")
            column.addWidget(hint)
            column.addStretch(1)
            return
        column.addLayout(self._heading(obj))
        own = [p for p in obj.props() if p.attr not in POSITION_ATTRS]
        position = [p for p in obj.props() if p.attr in POSITION_ATTRS]
        column.addWidget(section_label(tr("Settings")))
        column.addLayout(self._form(obj, own))
        self._hint = QLabel()
        self._hint.setWordWrap(True)
        set_tone(self._hint, "info")
        self._hint.setVisible(isinstance(obj, BarcodeObject))
        column.addWidget(self._hint)
        column.addWidget(section_label(tr("Position")))
        column.addLayout(self._form(obj, position))
        column.addStretch(1)
        self.refresh()

    def _heading(self, obj: LabelObject) -> QHBoxLayout:
        row = QHBoxLayout()
        pic = QLabel()
        pic.setPixmap(icon(KIND_ICONS.get(obj.kind, "square")).pixmap(20, 20))
        title = QLabel(obj.title)
        title.setObjectName("heading")
        row.addWidget(pic)
        row.addWidget(title, 1)
        return row

    def _form(self, obj: LabelObject, props: list[Prop]) -> QFormLayout:
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        for prop in props:
            if prop.kind == "image":
                form.addRow(self._image_row(obj))
                continue
            field = PropField(prop)
            field.setParent(self._content)
            field.changed.connect(lambda f=field: self._on_field(f))
            self._fields[prop.attr] = field
            if prop.kind == "bool":
                form.addRow(field.widget)
            elif prop.kind == "multiline":
                form.addRow(QLabel(prop.label))
                form.addRow(field.widget)
            else:
                form.addRow(prop.label, field.widget)
        return form

    def _image_row(self, obj: ImageObject) -> QHBoxLayout:
        row = QHBoxLayout()
        button = QPushButton(icon("image"), tr("Load image…"))
        button.clicked.connect(self.image_requested)
        name = QLabel(obj.name or tr("(no image)"))
        set_tone(name, "info")
        row.addWidget(button)
        row.addWidget(name, 1)
        return row

    # ------------------------------------------------------------------ syncing

    def _on_field(self, field: PropField) -> None:
        obj, value = self._obj, field.value()
        if obj is None or value is None or getattr(obj, field.prop.attr) == value:
            return
        self.document.set_property(obj, field.prop.attr, value)

    def refresh(self) -> None:
        obj = self._obj
        if obj is None or obj is not self.document.selected:
            return
        for attr, field in self._fields.items():
            field.show_value(getattr(obj, attr))
        rules = {"x": obj.h_align == "free"}
        if isinstance(obj, ImageObject):
            rules["threshold"] = not obj.dither
        if isinstance(obj, BarcodeObject):
            rules["text_size"] = obj.show_text
        if isinstance(obj, TextObject):
            rules["y"] = not obj.auto_size
        for attr, enabled in rules.items():
            if attr in self._fields:
                self._fields[attr].widget.setEnabled(enabled)
        if isinstance(obj, BarcodeObject):
            self._hint.setText(tr("Content: {rule}").format(rule=barcodes.rule(obj.symbology)))
        self._show_effective_size()

    def _show_effective_size(self) -> None:
        """Show the computed size of an automatically sized text without touching the document."""
        obj, field = self._obj, self._fields.get("size")
        if isinstance(obj, TextObject) and obj.auto_size and field is not None:
            placed = self.document.placed_of(obj)
            if placed and placed.size_pt:
                field.show_value(placed.size_pt)

    def focus_text(self) -> None:
        for attr in ("text", "data"):
            field = self._fields.get(attr)
            if field is not None and field.prop.kind in ("multiline", "text"):
                field.widget.setFocus()
                field.widget.selectAll()
                return

