"""The label being edited: undo history, selection, editing commands and rendering.

All views (canvas, panels, toolbars) change the document only through this controller and
update themselves from its signals.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from .. import fonts
from ..i18n import tr
from ..model import (BarcodeObject, FrameObject, ImageObject, LabelDocument, LabelObject, LineObject,
                     QRCodeObject, TextObject)
from ..render import Placed, RenderResult, image_aspect, render
from .qtutil import index_of


class UndoHistory:
    """Snapshots of the document as JSON."""

    LIMIT = 200

    def __init__(self, state: str = ""):
        self.reset(state)

    def reset(self, state: str) -> None:
        self._states = [state]
        self._pos = 0

    @property
    def current(self) -> str:
        return self._states[self._pos]

    @property
    def size(self) -> int:
        return len(self._states)

    def push(self, state: str) -> bool:
        if state == self.current:
            return False
        del self._states[self._pos + 1:]
        self._states.append(state)
        if len(self._states) > self.LIMIT:
            del self._states[0]
        self._pos = len(self._states) - 1
        return True

    def can_undo(self) -> bool:
        return self._pos > 0

    def can_redo(self) -> bool:
        return self._pos < len(self._states) - 1

    def undo(self) -> str | None:
        if not self.can_undo():
            return None
        self._pos -= 1
        return self.current

    def redo(self) -> str | None:
        if not self.can_redo():
            return None
        self._pos += 1
        return self.current


class DocumentController(QObject):
    changed = Signal()            # the content changed: views refresh their values
    reset = Signal()              # a new document or undo/redo replaced everything
    selection_changed = Signal()
    rendered = Signal()           # ``result`` is up to date
    render_failed = Signal(str)
    state_changed = Signal()      # path, modified flag or undo/redo availability

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.doc = LabelDocument()
        self.path: Path | None = None
        self.selected: LabelObject | None = None
        self.result: RenderResult | None = None
        self.history = UndoHistory(self.doc.to_json())
        self._saved = self.history.current
        self._commit_timer = QTimer(self, singleShot=True, interval=500)
        self._commit_timer.timeout.connect(self.commit)
        self._render_timer = QTimer(self, singleShot=True, interval=0)
        self._render_timer.timeout.connect(self.render_now)

    # ------------------------------------------------------------------ document lifecycle

    def new(self, tape_mm: float = 12.0) -> None:
        doc = LabelDocument(tape_mm=tape_mm)
        doc.objects.append(TextObject(x=doc.margin_mm, font=fonts.REGISTRY.default_family()))
        self._replace(doc, None)
        self.select(doc.objects[0])

    def open(self, path: str | Path) -> None:
        self._replace(LabelDocument.load(path), Path(path))

    def save(self, path: str | Path | None = None) -> None:
        self.flush()
        target = Path(path) if path else self.path
        if target is None:
            raise ValueError("no file name")
        self.doc.save(target)
        self.path = target
        self._saved = self.doc.to_json()
        self.state_changed.emit()

    def _replace(self, doc: LabelDocument, path: Path | None) -> None:
        self._commit_timer.stop()
        self.doc, self.path, self.selected = doc, path, None
        state = doc.to_json()
        self.history.reset(state)
        self._saved = state
        self._after_reset()

    def _after_reset(self) -> None:
        self.reset.emit()
        self.selection_changed.emit()
        self.state_changed.emit()
        self.schedule_render()

    def is_modified(self) -> bool:
        return self.doc.to_json() != self._saved

    def is_pristine(self) -> bool:
        """Untouched new document that may be replaced silently."""
        return self.path is None and self.history.size == 1 and not self.is_modified()

    @property
    def name(self) -> str:
        return self.path.name if self.path else tr("Untitled")

    # ------------------------------------------------------------------ undo

    def edited(self, commit: bool = False, record: bool = True) -> None:
        """Call after every change of the document.

        ``commit`` records an undo step now; otherwise one is recorded after a short pause,
        unless ``record`` is False (e.g. while dragging, the release commits).
        """
        self.changed.emit()
        self.schedule_render()
        if commit:
            self.commit()
        elif record:
            self._commit_timer.start()

    def commit(self) -> None:
        self._commit_timer.stop()
        self.history.push(self.doc.to_json())
        self.state_changed.emit()

    def flush(self) -> None:
        if self._commit_timer.isActive():
            self.commit()

    def undo(self) -> None:
        self.flush()
        self._restore(self.history.undo())

    def redo(self) -> None:
        self.flush()
        self._restore(self.history.redo())

    def _restore(self, state: str | None) -> None:
        if state is None:
            return
        index = index_of(self.doc.objects, self.selected)
        self.doc = LabelDocument.from_json(state)
        objects = self.doc.objects
        self.selected = objects[index] if index is not None and index < len(objects) else None
        self._after_reset()

    # ------------------------------------------------------------------ selection

    def select(self, obj: LabelObject | None) -> None:
        if obj is not self.selected:
            self.selected = obj
            self.selection_changed.emit()

    def placed_of(self, obj: LabelObject | None) -> Placed | None:
        if self.result is None or obj is None:
            return None
        return next((p for p in self.result.placed if p.obj is obj), None)

    # ------------------------------------------------------------------ object commands

    def create_object(self, kind: str, image: tuple[str, str, float] | None = None) -> LabelObject:
        """New object of ``kind`` placed right of the existing ones; ``image`` = (data, name, aspect)."""
        tape = self.doc.tape
        top, band = round(tape.band_top_mm, 2), round(tape.print_mm, 1)
        x = self._next_x()
        if kind == "text":
            return TextObject(x=x, y=top, font=fonts.REGISTRY.default_family())
        if kind == "qrcode":
            return QRCodeObject(x=x, y=top, size=band)
        if kind == "barcode":
            return BarcodeObject(x=x, y=top, height=band, show_text=band >= 6)
        if kind == "image":
            data, name, aspect = image
            return ImageObject(x=x, y=top, data=data, name=name, height=band, width=round(band * aspect, 1))
        if kind == "frame":
            length = (self.result.length_mm if self.result else 40) - 2 * self.doc.margin_mm
            return FrameObject(x=self.doc.margin_mm, y=top, width=round(max(5.0, length), 1), height=band)
        return LineObject(x=x, y=round(top + band / 2 - 0.2, 2), length=20)

    def _next_x(self) -> float:
        if not self.result or not self.result.placed:
            return self.doc.margin_mm
        right = max(p.box[2] for p in self.result.placed) / self.result.scale
        return round(right + 1.5, 1)

    def add_object(self, obj: LabelObject) -> None:
        self.doc.objects.append(obj)
        self.select(obj)
        self.edited(commit=True)

    def delete_selected(self) -> None:
        index = index_of(self.doc.objects, self.selected)
        if index is not None:
            del self.doc.objects[index]
            self.select(None)
            self.edited(commit=True)

    def duplicate_selected(self) -> None:
        if self.selected is None:
            return
        copy = self.selected.copy()
        copy.x += 2
        if not (isinstance(copy, TextObject) and copy.auto_size):
            copy.y += 1
        self.add_object(copy)

    def restack(self, direction: int) -> None:
        """Move the selected object one step to the front (+1) or back (-1)."""
        objects = self.doc.objects
        index = index_of(objects, self.selected)
        if index is not None:
            target = max(0, min(len(objects) - 1, index + direction))
            objects.insert(target, objects.pop(index))
            self.edited(commit=True)

    def reorder(self, objects: list[LabelObject]) -> None:
        """Set a new stacking order (back to front) of the same objects."""
        if sorted(map(id, objects)) == sorted(map(id, self.doc.objects)):
            self.doc.objects[:] = objects
            self.edited(commit=True)

    def center_vertically(self) -> None:
        obj, placed = self.selected, self.placed_of(self.selected)
        if obj is None or placed is None or (isinstance(obj, TextObject) and obj.auto_size):
            return
        top, bottom = self.result.band
        height = placed.box[3] - placed.box[1]
        obj.y = round((top + (bottom - top - height) / 2) / self.result.scale, 2)
        self.edited(commit=True)

    def center_horizontally(self) -> None:
        if self.selected is not None:
            self.set_property(self.selected, "h_align", "center")
            self.commit()

    def release_anchor(self, obj: LabelObject) -> None:
        """Make a centered or right-aligned object free again, at the place where it is now."""
        placed = self.placed_of(obj)
        if obj.h_align != "free" and placed and self.result:
            obj.x = round(placed.box[0] / self.result.scale, 2)
        obj.h_align = "free"

    def nudge(self, dx: float, dy: float) -> None:
        obj = self.selected
        if obj is not None:
            if dx:
                self.release_anchor(obj)
            obj.x = round(obj.x + dx, 2)
            if not (isinstance(obj, TextObject) and obj.auto_size):
                obj.y = round(obj.y + dy, 2)
            self.edited()

    def set_property(self, obj: LabelObject, attr: str, value) -> None:
        if isinstance(obj, TextObject) and (attr == "size" or (attr == "auto_size" and not value)):
            self.freeze_auto_text(obj)
        if attr == "h_align" and value == "free":
            self.release_anchor(obj)
        setattr(obj, attr, value)
        if isinstance(obj, ImageObject) and obj.keep_aspect and attr in ("width", "height", "keep_aspect"):
            aspect = image_aspect(obj)
            if aspect:
                if attr == "height":
                    obj.width = round(obj.height * aspect, 1)
                else:
                    obj.height = round(obj.width / aspect, 1)
        self.edited()

    def set_image(self, obj: ImageObject, data: str, name: str, aspect: float) -> None:
        obj.data, obj.name = data, name
        if obj.keep_aspect:
            obj.width = round(obj.height * aspect, 1)
        self.edited(commit=True)

    def freeze_auto_text(self, obj: TextObject) -> None:
        """Turn an automatically sized text into a fixed one at its current size and position."""
        placed = self.placed_of(obj)
        if obj.auto_size and placed and self.result:
            obj.size = placed.size_pt or obj.size
            obj.y = round(placed.box[1] / self.result.scale, 2)
            obj.auto_size = False

    # ------------------------------------------------------------------ label and print settings

    def set_label(self, tape_mm: float | None = None, auto_length: bool | None = None,
                  length_mm: float | None = None, margin_mm: float | None = None) -> None:
        doc = self.doc
        if tape_mm is not None:
            doc.tape_mm = tape_mm
        if auto_length is not None and auto_length != doc.auto_length:
            if not auto_length and self.result:
                doc.length_mm = round(self.result.length_mm, 1)  # start from the current length
            doc.auto_length = auto_length
        if length_mm is not None:
            doc.length_mm = length_mm
        if margin_mm is not None and margin_mm != doc.margin_mm:
            shift = margin_mm - doc.margin_mm  # keep every object at its distance from the margin
            for obj in doc.objects:
                obj.x = round(obj.x + shift, 2)
            doc.margin_mm = margin_mm
        self.edited()

    def set_print_options(self, **values) -> None:
        for attr, value in values.items():
            setattr(self.doc, attr, value)
        self.edited()

    # ------------------------------------------------------------------ rendering

    def schedule_render(self) -> None:
        if not self._render_timer.isActive():
            self._render_timer.start()

    def render_now(self) -> None:
        self._render_timer.stop()
        try:
            self.result = render(self.doc)
        except Exception as exc:  # keep the editor alive on unexpected input
            self.render_failed.emit(str(exc))
            return
        self.rendered.emit()
