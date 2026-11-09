"""The Edit Text tool's in-place editor: one line of page text, with its font size and color."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QRectF, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QDoubleSpinBox, QHBoxLayout, QLineEdit, QWidget

from .dialogs import ColorButton

# losing focus for these reasons means the user went elsewhere; a popup (the color menu) or a window switch
# does not end the edit
LEAVING = {Qt.MouseFocusReason, Qt.TabFocusReason, Qt.BacktabFocusReason, Qt.OtherFocusReason}


class InlineTextEditor(QWidget):
    committed = Signal()                    # Enter, or focus moved elsewhere: keep the text as it is now
    cancelled = Signal()                    # Escape

    def __init__(self, parent, text: str, size: float, color, zoom: float):
        super().__init__(parent)
        self.zoom = zoom
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)
        self.edit = QLineEdit(text)
        self.edit.setStyleSheet("background:#fffbe6;border:1px solid #1e64ff;")
        self.spin = QDoubleSpinBox(minimum=2, maximum=200, value=size, decimals=1, singleStep=0.5)
        self.spin.setToolTip("Font size")
        self.spin.setFixedWidth(64)
        self.swatch = ColorButton(tuple(color) if color else (0, 0, 0))
        self.swatch.setToolTip("Text color")
        self.swatch.setFixedSize(26, 26)
        for w in (self.edit, self.spin, self.swatch):
            row.addWidget(w)
        self.spin.valueChanged.connect(self._refit)
        self.edit.returnPressed.connect(self.committed)
        self.edit.installEventFilter(self)
        self._refit()

    def _refit(self):
        f = QFont()
        f.setPixelSize(max(8, int(self.spin.value() * self.zoom * 0.95)))
        self.edit.setFont(f)

    def place(self, r: QRectF):
        """Cover the line's box on screen, with room for the controls."""
        self.setGeometry(int(r.x()) - 2, int(r.y()) - 2, max(int(r.width()) + 170, 260), max(int(r.height()) + 6, 26))

    def focus(self):
        self.edit.setFocus()
        self.edit.selectAll()

    def text(self) -> str:
        return self.edit.text()

    def setText(self, text: str):
        self.edit.setText(text)

    def size(self) -> float:
        return self.spin.value()

    def color(self) -> tuple | None:
        return tuple(self.swatch.rgb) if self.swatch.rgb else None

    def eventFilter(self, obj, ev):
        if obj is self.edit:
            if ev.type() == QEvent.Type.KeyPress and ev.key() == Qt.Key_Escape:
                self.cancelled.emit()
                return True
            if ev.type() == QEvent.Type.FocusOut and ev.reason() in LEAVING:
                w = QApplication.focusWidget()
                if QApplication.activePopupWidget() is None and (w is None or not self.isAncestorOf(w)):
                    self.committed.emit()
        return super().eventFilter(obj, ev)
