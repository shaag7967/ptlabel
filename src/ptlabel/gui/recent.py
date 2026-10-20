"""Recently used label files."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMenu

from ..i18n import tr
from .icons import icon

LIMIT = 8


class RecentFiles(QObject):
    open_requested = Signal(str)

    def __init__(self, cfg: dict, parent: QObject | None = None):
        super().__init__(parent)
        self.cfg = cfg
        self.menu = QMenu(tr("Open recent"))
        self.menu.setIcon(icon("history"))
        self.menu.aboutToShow.connect(self._fill)

    @property
    def files(self) -> list[str]:
        return [f for f in self.cfg.get("recent", []) if isinstance(f, str)]

    def add(self, path: Path) -> None:
        name = str(path)
        self.cfg["recent"] = [name] + [f for f in self.files if f != name][:LIMIT - 1]

    def _fill(self) -> None:
        self.menu.clear()
        files = [f for f in self.files if Path(f).exists()]
        for name in files:
            action = self.menu.addAction(Path(name).name)
            action.setToolTip(name)
            action.setStatusTip(name)
            action.triggered.connect(lambda _=False, n=name: self.open_requested.emit(n))
        if not files:
            self.menu.addAction(tr("No recent files")).setEnabled(False)
        else:
            self.menu.addSeparator()
            self.menu.addAction(tr("Clear list"), self._clear)

    def _clear(self) -> None:
        self.cfg["recent"] = []
