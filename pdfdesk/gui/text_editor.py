"""Editors that sit on the page, so text is typed where it goes:

- ``InlineTextEditor``: one line of page text (Edit Text), new text (Typewriter, Add Text) or a text comment's
  text, with its font size and color;
- ``InlineFieldEditor``: a form field's value (text, combo box, list box); Tab moves on to the next field.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QRectF, Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QSizePolicy,
    QWidget,
)

from ..lang import tr
from .dialogs import ColorButton

# losing focus for these reasons means the user went elsewhere; a popup (the color menu) or a window switch
# does not end the edit
LEAVING = {Qt.MouseFocusReason, Qt.TabFocusReason, Qt.BacktabFocusReason, Qt.OtherFocusReason}
CONTROLS_W = 100                        # room for the size box and the color swatch


def _left_for_good(editor: QWidget, ev) -> bool:
    if ev.type() != QEvent.Type.FocusOut or ev.reason() not in LEAVING:
        return False
    w = QApplication.focusWidget()
    return QApplication.activePopupWidget() is None and (w is None or not editor.isAncestorOf(w))


class InlineTextEditor(QWidget):
    committed = Signal()                    # Enter (single line), Ctrl+Enter, or focus moved elsewhere
    cancelled = Signal()                    # Escape (unless escape_keeps)

    def __init__(self, parent, text: str, size: float, color, zoom: float, multiline: bool = False,
                 escape_keeps: bool = False, controls: bool = True):
        super().__init__(parent)
        self.zoom = zoom
        self.multiline = multiline
        self.escape_keeps = escape_keeps
        self._box = QRectF()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)
        if multiline:
            self.edit = QPlainTextEdit(text)
            self.edit.setLineWrapMode(QPlainTextEdit.NoWrap)
            self.edit.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.edit.textChanged.connect(self._grow)
        else:
            self.edit = QLineEdit(text)
            self.edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)   # as tall as the line: text centred on it
            self.edit.returnPressed.connect(self.committed)
            self.edit.textChanged.connect(self._grow)
        self.edit.setStyleSheet("background:#fffbe6;border:1px solid #1e64ff;")
        self.spin = QDoubleSpinBox(minimum=2, maximum=200, value=size, decimals=1, singleStep=0.5)
        self.spin.setToolTip(tr("Font size"))
        self.spin.setFixedWidth(64)
        self.swatch = ColorButton(tuple(color) if color else (0, 0, 0))
        self.swatch.setToolTip(tr("Text color"))
        self.swatch.setFixedSize(26, 26)
        for w in (self.spin, self.swatch):          # light controls next to the page, whatever the window style
            w.setStyleSheet("background:#ffffff;color:#000000;border:1px solid #1e64ff;")
        row.addWidget(self.edit, 1)
        row.addWidget(self.spin, 0, Qt.AlignTop)
        row.addWidget(self.swatch, 0, Qt.AlignTop)
        self.controls = controls
        self.spin.setVisible(controls)
        self.swatch.setVisible(controls)
        self.spin.valueChanged.connect(self._refit)
        self.swatch.changed.connect(lambda _c: self._refit())
        self.edit.installEventFilter(self)
        self._refit()

    def _font(self) -> QFont:
        f = QFont()
        f.setPixelSize(max(8, int(self.spin.value() * self.zoom * 0.95)))
        return f

    def _refit(self):
        self.edit.setFont(self._font())
        c = self.swatch.rgb or (0, 0, 0)
        self.edit.setStyleSheet("background:#fffbe6;border:1px solid #1e64ff;color:rgb(%d,%d,%d)"
                                % tuple(round(v * 255) for v in c))
        self._grow()

    def _grow(self):
        """Keep the whole text visible while it is typed: wider for a longer line, taller for more lines."""
        if self._box.isNull():
            return
        fm = QFontMetrics(self._font())
        lines = self.text().split("\n") or [""]
        w = max(fm.horizontalAdvance(ln) for ln in lines) + fm.averageCharWidth() * 3 + 12
        h = fm.lineSpacing() * len(lines) + 12
        width = max(int(self._box.width()) + 6, w, 160) + (CONTROLS_W if self.controls else 0)
        if self.parentWidget() is not None:
            width = min(width, max(200, self.parentWidget().width() - int(self._box.x())))
        self.setGeometry(int(self._box.x()) - 3, int(self._box.y()) - 3, width,
                         max(int(self._box.height()) + 6, h, 26))

    def place(self, r: QRectF):
        """Cover the text's box on screen (view coordinates), with room for the controls."""
        self._box = QRectF(r)
        self._grow()

    def focus(self):
        self.edit.setFocus()
        self.edit.selectAll()

    def text(self) -> str:
        return self.edit.toPlainText() if self.multiline else self.edit.text()

    def setText(self, text: str):
        if self.multiline:
            self.edit.setPlainText(text)
        else:
            self.edit.setText(text)

    def size(self) -> float:
        return self.spin.value()

    def color(self) -> tuple | None:
        return tuple(self.swatch.rgb) if self.swatch.rgb else None

    def eventFilter(self, obj, ev):
        if obj is self.edit:
            if ev.type() == QEvent.Type.KeyPress:
                if ev.key() == Qt.Key_Escape:
                    (self.committed if self.escape_keeps else self.cancelled).emit()
                    return True
                if self.multiline and ev.key() in (Qt.Key_Return, Qt.Key_Enter) and ev.modifiers() & Qt.ControlModifier:
                    self.committed.emit()
                    return True
            if _left_for_good(self, ev):
                self.committed.emit()
        return super().eventFilter(obj, ev)


class InlineFieldEditor(QWidget):
    """A form field's value typed or picked on the page. committed(step): 0 to stay, 1 / -1 to move on to the
    next / previous field (Tab / Shift+Tab)."""
    committed = Signal(int)
    cancelled = Signal()

    def __init__(self, parent, kind: str, value: str, options: list[str], pixel_size: int, multiline: bool = False,
                 editable: bool = False):
        super().__init__(parent)
        self.kind = kind
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        f = QFont()
        f.setPixelSize(max(9, pixel_size))
        if kind in ("combo", "list"):
            self.edit = QComboBox()
            self.edit.addItems(options)
            self.edit.setEditable(editable)
            if value in options:
                self.edit.setCurrentIndex(options.index(value))
            elif editable:
                self.edit.setEditText(value)
            self.edit.activated.connect(lambda _i: self.committed.emit(0))
        elif multiline:
            self.edit = QPlainTextEdit(value)
        else:
            self.edit = QLineEdit(value)
            self.edit.returnPressed.connect(lambda: self.committed.emit(0))
        self.edit.setFont(f)
        self.edit.setStyleSheet("background:#eef4ff;border:1px solid #1e64ff;")
        lay.addWidget(self.edit)
        self.edit.installEventFilter(self)
        if isinstance(self.edit, QComboBox) and self.edit.lineEdit():
            self.edit.lineEdit().installEventFilter(self)

    def place(self, r: QRectF):
        self.setGeometry(int(r.x()) - 1, int(r.y()) - 1, max(int(r.width()) + 2, 40), max(int(r.height()) + 2, 20))

    def focus(self):
        self.edit.setFocus()
        if isinstance(self.edit, QLineEdit):
            self.edit.selectAll()
        elif isinstance(self.edit, QComboBox) and not self.edit.isEditable():
            self.edit.showPopup()

    def value(self) -> str:
        if isinstance(self.edit, QComboBox):
            return self.edit.currentText()
        return self.edit.toPlainText() if isinstance(self.edit, QPlainTextEdit) else self.edit.text()

    def setValue(self, v: str):
        if isinstance(self.edit, QComboBox):
            self.edit.setEditText(v) if self.edit.isEditable() else self.edit.setCurrentText(v)
        elif isinstance(self.edit, QPlainTextEdit):
            self.edit.setPlainText(v)
        else:
            self.edit.setText(v)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.KeyPress:
            if ev.key() == Qt.Key_Escape:
                self.cancelled.emit()
                return True
            if ev.key() == Qt.Key_Tab:
                self.committed.emit(1)
                return True
            if ev.key() == Qt.Key_Backtab:
                self.committed.emit(-1)
                return True
            if isinstance(self.edit, QPlainTextEdit) and ev.key() in (Qt.Key_Return, Qt.Key_Enter) \
                    and ev.modifiers() & Qt.ControlModifier:
                self.committed.emit(0)
                return True
        if _left_for_good(self, ev):
            self.committed.emit(0)
        return super().eventFilter(obj, ev)
