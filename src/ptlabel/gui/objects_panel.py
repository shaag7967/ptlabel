"""Dock content listing all objects of the label; the topmost entry is in front."""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, QSize, Qt, QTimer
from PySide6.QtWidgets import QAbstractItemView, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from ..i18n import tr
from ..model import BarcodeObject, FrameObject, ImageObject, LabelObject, LineObject, QRCodeObject, TextObject
from .document import DocumentController
from .icons import icon
from .properties import KIND_ICONS
from .qtutil import fmt

ROLE = Qt.ItemDataRole.UserRole


def describe(obj: LabelObject) -> str:
    """Short summary shown next to the object type."""
    if isinstance(obj, TextObject):
        return obj.text.split("\n", 1)[0]
    if isinstance(obj, (QRCodeObject, BarcodeObject)):
        return obj.data.split("\n", 1)[0]
    if isinstance(obj, ImageObject):
        return obj.name or tr("(no image)")
    if isinstance(obj, FrameObject):
        return f"{fmt(obj.width)} × {fmt(obj.height)} mm"
    if isinstance(obj, LineObject):
        return f"{fmt(obj.length)} mm"
    return ""


class ObjectsPanel(QWidget):
    def __init__(self, document: DocumentController):
        super().__init__()
        self.document = document
        self.list = QListWidget()
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.list.setIconSize(QSize(18, 18))
        self.list.setAlternatingRowColors(True)
        self.list.setMinimumWidth(150)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.list.setToolTip(tr("Drag entries to change which object is in front"))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self.list)

        self.list.currentItemChanged.connect(self._on_current)
        self.list.model().rowsMoved.connect(lambda *_: QTimer.singleShot(0, self._on_moved))
        document.reset.connect(self.rebuild)
        document.changed.connect(self.rebuild)
        document.selection_changed.connect(self._select_current)
        self.rebuild()

    def _objects_front_first(self) -> list[LabelObject]:
        return list(reversed(self.document.doc.objects))

    def rebuild(self) -> None:
        objects = self._objects_front_first()
        with QSignalBlocker(self.list):
            shown = [id(self.list.item(i).data(ROLE)) for i in range(self.list.count())]
            if shown != [id(obj) for obj in objects]:  # identity: equal copies are different objects
                self.list.clear()
                for obj in objects:
                    item = QListWidgetItem(icon(KIND_ICONS.get(obj.kind, "square")), "")
                    item.setData(ROLE, obj)
                    self.list.addItem(item)
            for i in range(self.list.count()):
                item = self.list.item(i)
                obj = item.data(ROLE)
                text = describe(obj)
                item.setText(f"{obj.title}  ·  {text}" if text else obj.title)
        self._select_current()

    def _select_current(self) -> None:
        selected = self.document.selected
        with QSignalBlocker(self.list):
            for i in range(self.list.count()):
                if self.list.item(i).data(ROLE) is selected:
                    self.list.setCurrentRow(i)
                    return
            self.list.setCurrentRow(-1)

    def _on_current(self, item: QListWidgetItem | None, _previous=None) -> None:
        self.document.select(item.data(ROLE) if item else None)

    def _on_moved(self) -> None:
        front_first = [self.list.item(i).data(ROLE) for i in range(self.list.count())]
        self.document.reorder(list(reversed(front_first)))
