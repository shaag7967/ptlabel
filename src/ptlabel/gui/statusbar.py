"""Status bar: messages, printer state, loaded tape, label size and zoom."""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSlider, QStatusBar, QToolButton, QWidget

from ..i18n import tr
from .canvas import MAX_ZOOM, LabelCanvas
from .document import DocumentController
from .icons import icon
from .printing import PrinterController
from .qtutil import set_tone
from .widgets import ColorSwatch, StatusDot

MESSAGE_MS = 6000


class ZoomControl(QWidget):
    def __init__(self, canvas: LabelCanvas):
        super().__init__()
        self.canvas = canvas
        out_button, in_button, fit = QToolButton(), QToolButton(), QToolButton()
        out_button.setIcon(icon("zoom-out"))
        out_button.setToolTip(tr("Zoom out"))
        in_button.setIcon(icon("zoom-in"))
        in_button.setToolTip(tr("Zoom in"))
        fit.setIcon(icon("scan"))
        fit.setToolTip(tr("Automatic zoom"))
        fit.setCheckable(True)
        self.fit = fit
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(1, MAX_ZOOM)
        self.slider.setFixedWidth(110)
        self.label = QLabel()
        self.label.setMinimumWidth(42)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        for widget in (fit, out_button, self.slider, in_button, self.label):
            layout.addWidget(widget)
        out_button.clicked.connect(lambda: canvas.zoom_by(-1))
        in_button.clicked.connect(lambda: canvas.zoom_by(1))
        fit.clicked.connect(lambda on: canvas.set_zoom(0 if on else round(canvas.effective_zoom())))
        self.slider.valueChanged.connect(canvas.set_zoom)
        canvas.zoom_changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        z = self.canvas.effective_zoom()
        with QSignalBlocker(self.slider):
            self.slider.setValue(round(z))
        self.fit.setChecked(self.canvas.zoom == 0)
        self.label.setText(f"{z:g}×")


class StatusBar(QStatusBar):
    adopt_tape_requested = Signal()
    printer_clicked = Signal()

    def __init__(self, document: DocumentController, printer: PrinterController, canvas: LabelCanvas, theme):
        super().__init__()
        self.document, self.printer, self.theme = document, printer, theme
        self.setSizeGripEnabled(False)

        self.message = QLabel()
        self._message_timer = QTimer(self, singleShot=True, interval=MESSAGE_MS)
        self._message_timer.timeout.connect(self.message.clear)

        self.printer_button = QToolButton()
        self.printer_button.setAutoRaise(True)
        self.printer_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.printer_button.setToolTip(tr("Query status"))
        self.printer_button.clicked.connect(self.printer_clicked)
        self.dot = StatusDot()
        self.swatch = ColorSwatch()
        self.adopt = QPushButton(icon("check"), "")
        self.adopt.clicked.connect(self.adopt_tape_requested)
        self.warning = QLabel()
        set_tone(self.warning, "warn")
        self.size = QLabel()

        self.addWidget(self.dot)
        self.addWidget(self.printer_button)
        self.addWidget(self.swatch)
        self.addWidget(self.adopt)
        self.addWidget(self.message, 1)
        self.addPermanentWidget(self.warning)
        self.addPermanentWidget(self.size)
        self.addPermanentWidget(ZoomControl(canvas))

        printer.status_changed.connect(self.refresh_printer)
        document.reset.connect(self.refresh_printer)
        document.changed.connect(self.refresh_printer)
        document.rendered.connect(self.refresh_label)
        document.render_failed.connect(lambda text: self.show_message(
            tr("Rendering error: {error}").format(error=text), "error"))
        theme.changed.connect(self.refresh_printer)
        self.refresh_printer()

    def show_message(self, text: str, tone: str = "info", sticky: bool = False) -> None:
        self.message.setText(text)
        set_tone(self.message, tone)
        if sticky:
            self._message_timer.stop()
        else:
            self._message_timer.start()

    def refresh_printer(self) -> None:
        printer = self.printer
        text = printer.text if len(printer.text) < 70 else printer.text[:67] + "…"
        self.printer_button.setText(text)
        self.dot.set_color(self.theme.tone_color(printer.tone))
        status = printer.status
        self.swatch.set_colors(status.tape_color_rgb if status else None, status.text_color_rgb if status else None)
        tape = printer.tape
        mismatch = tape is not None and tape.code != self.document.doc.tape.code
        self.adopt.setVisible(mismatch)
        if mismatch:
            self.adopt.setText(tr("Use loaded tape ({tape})").format(tape=tape.label))

    def refresh_label(self) -> None:
        result = self.document.result
        if result is None:
            return
        text = f"{result.tape.label} × {result.length_mm:.1f} mm"
        if result.wrap:
            text += "  " + tr("(flag {length:.1f} mm)").format(length=result.face_mm)
        self.size.setText(text)
        self.warning.setText(" · ".join(dict.fromkeys(result.warnings)))
