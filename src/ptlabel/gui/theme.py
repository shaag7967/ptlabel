"""Light and dark theme on top of Qt's Fusion style; "system" follows the desktop setting."""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

MODES = ("system", "light", "dark")

R = QPalette.ColorRole
LIGHT = {
    R.Window: "#f3f4f6", R.WindowText: "#1f2328", R.Base: "#ffffff", R.AlternateBase: "#f0f2f5",
    R.ToolTipBase: "#ffffff", R.ToolTipText: "#1f2328", R.PlaceholderText: "#868c96", R.Text: "#1f2328",
    R.Button: "#f7f8fa", R.ButtonText: "#1f2328", R.BrightText: "#ffffff", R.Light: "#ffffff",
    R.Midlight: "#e9ebef", R.Mid: "#cfd3da", R.Dark: "#a3a9b3", R.Shadow: "#6b7280",
    R.Highlight: "#2f6fe4", R.HighlightedText: "#ffffff", R.Link: "#2f6fe4", R.LinkVisited: "#7a4fd8",
    R.Accent: "#2f6fe4",
}
DARK = {
    R.Window: "#1f2125", R.WindowText: "#e4e6ea", R.Base: "#16181b", R.AlternateBase: "#24272c",
    R.ToolTipBase: "#2a2d33", R.ToolTipText: "#e4e6ea", R.PlaceholderText: "#7d838d", R.Text: "#e4e6ea",
    R.Button: "#2a2d33", R.ButtonText: "#e4e6ea", R.BrightText: "#ffffff", R.Light: "#3a3e45",
    R.Midlight: "#30343a", R.Mid: "#3d4148", R.Dark: "#121316", R.Shadow: "#000000",
    R.Highlight: "#4c8dff", R.HighlightedText: "#ffffff", R.Link: "#6ea2ff", R.LinkVisited: "#a98bff",
    R.Accent: "#4c8dff",
}
TONE_COLORS = {
    False: {"info": "#5f6670", "ok": "#1e7b34", "warn": "#9a5b00", "error": "#c01c28", "busy": "#2f6fe4"},
    True: {"info": "#9aa1ab", "ok": "#57c27a", "warn": "#e6a23c", "error": "#ff6b6b", "busy": "#6ea2ff"},
}
CANVAS_BACKGROUND = {False: "#d5d9df", True: "#111214"}

STYLE = """
QToolBar {{ border: none; spacing: 2px; padding: 3px 4px; }}
QToolBar::separator {{ width: 1px; margin: 4px 6px; background: palette(mid); }}
QToolButton {{ padding: 4px; border-radius: 6px; }}
QToolButton:hover {{ background: palette(midlight); }}
QToolButton:checked {{ background: palette(mid); }}
QDockWidget::title {{ padding: 7px 8px; font-weight: 600; background: palette(window); }}
QStatusBar {{ border-top: 1px solid palette(mid); }}
QStatusBar::item {{ border: none; }}
QPushButton#primary {{
    background: palette(highlight); color: palette(highlighted-text); border: none;
    border-radius: 6px; padding: 7px 16px; font-weight: 600;
}}
QPushButton#primary:hover {{ background: {accent_hover}; }}
QPushButton#primary:disabled {{ background: palette(mid); color: palette(window-text); }}
QLabel#section {{ color: palette(placeholder-text); font-weight: 600; padding-top: 6px; }}
QLabel#heading {{ font-size: 13pt; font-weight: 600; }}
QFrame#card {{ background: palette(base); border: 1px solid palette(mid); border-radius: 8px; }}
QLabel[tone="info"] {{ color: {info}; }}
QLabel[tone="ok"] {{ color: {ok}; }}
QLabel[tone="warn"] {{ color: {warn}; }}
QLabel[tone="error"] {{ color: {error}; }}
QLabel[tone="busy"] {{ color: {busy}; }}
"""


def system_is_dark() -> bool:
    return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark


class ThemeManager(QObject):
    """Applies palette and style sheet; emits ``changed`` whenever the look changes."""

    changed = Signal()

    def __init__(self, app: QApplication, mode: str = "system"):
        super().__init__(app)
        self.app = app
        self.mode = mode if mode in MODES else "system"
        self.dark = False
        app.setStyle("Fusion")
        app.styleHints().colorSchemeChanged.connect(self._system_changed)
        self.apply()

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.apply()

    def _system_changed(self, *_) -> None:
        if self.mode == "system":
            self.apply()

    def apply(self) -> None:
        self.dark = self.mode == "dark" or (self.mode == "system" and system_is_dark())
        colors = DARK if self.dark else LIGHT
        palette = QPalette()
        for role, color in colors.items():
            palette.setColor(role, QColor(color))
        disabled = QColor(colors[R.PlaceholderText])
        for role in (R.WindowText, R.Text, R.ButtonText):
            palette.setColor(QPalette.ColorGroup.Disabled, role, disabled)
        self.app.setPalette(palette)
        accent_hover = QColor(colors[R.Highlight]).lighter(112).name()
        self.app.setStyleSheet(STYLE.format(accent_hover=accent_hover, **TONE_COLORS[self.dark]))
        self.changed.emit()

    @property
    def canvas_background(self) -> QColor:
        return QColor(CANVAS_BACKGROUND[self.dark])

    def tone_color(self, tone: str) -> QColor:
        return QColor(TONE_COLORS[self.dark].get(tone, TONE_COLORS[self.dark]["info"]))
