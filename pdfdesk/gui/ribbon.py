"""Ribbon laid out like Foxit PhantomPDF: tab row (File tab, tabs, Tell-me box, Find box), then groups of
large buttons, stacked small buttons and icon grids, each group named underneath."""
from __future__ import annotations

from PySide6.QtCore import QSize, QStringListModel, Qt, Signal
from PySide6.QtWidgets import (QCompleter, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu,
                               QSizePolicy, QStackedWidget, QTabBar, QToolButton, QVBoxLayout, QWidget)

from .icons import icon

STYLE = """
QTabBar::tab { padding: 6px 12px; border: none; background: transparent; color: #333; }
QTabBar::tab:selected { background: #fff; border-top: 2px solid #6b2d7b; color: #000; }
QTabBar::tab:hover:!selected { background: #ece6ef; }
QTabBar::tab:first { background: #6b2d7b; color: #fff; padding: 6px 20px; font-weight: bold; }
QTabBar::tab:first:hover { background: #81419a; }
#ribbonBody { background: #fff; border-top: 1px solid #d5d5d5; border-bottom: 1px solid #d5d5d5; }
#ribbonRow { background: #f3f3f3; }
QToolButton { border: 1px solid transparent; border-radius: 3px; padding: 2px; background: transparent; color: #222; }
QToolButton:hover { background: #ece6ef; border-color: #cdb8d6; }
QToolButton:checked { background: #dccbe3; border-color: #6b2d7b; }
QToolButton::menu-indicator { image: none; }
"""


class Ribbon(QWidget):
    tabChanged = Signal(str)

    def __init__(self):
        super().__init__()
        self.setStyleSheet(STYLE)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        row = QWidget()
        row.setObjectName("ribbonRow")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 6, 0)
        rl.setSpacing(6)
        self.bar = QTabBar()
        self.bar.setExpanding(False)
        self.bar.setDrawBase(False)
        rl.addWidget(self.bar)
        rl.addStretch(1)
        self.tellme = QLineEdit(placeholderText="💡 Tell me what you want to do…")
        self.tellme.setFixedWidth(240)
        self.find = QLineEdit(placeholderText="Find")
        self.find.setFixedWidth(190)
        rl.addWidget(self.tellme)
        rl.addWidget(self.find)
        v.addWidget(row)
        self.stack = QStackedWidget()
        self.stack.setObjectName("ribbonBody")
        self.stack.setFixedHeight(98)
        v.addWidget(self.stack)
        self.bar.currentChanged.connect(self._changed)
        self.pages: dict[str, QHBoxLayout] = {}
        self._names: list[str] = []
        self._catalog: dict[str, callable] = {}
        self._completer_model = QStringListModel()
        comp = QCompleter(self._completer_model, self.tellme)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        self.tellme.setCompleter(comp)
        comp.activated.connect(self._run_catalog)
        self.tellme.returnPressed.connect(lambda: self._run_catalog(self.tellme.text()))

    # ---- tabs --------------------------------------------------------------------------------------
    def add_tab(self, name: str):
        name = name.replace("&&", "&")
        self.bar.addTab(name.replace("&", "&&"))      # QTabBar treats a single & as a shortcut marker
        page = QWidget()
        lay = QHBoxLayout(page)
        lay.setContentsMargins(6, 4, 6, 2)
        lay.setSpacing(0)
        lay.setAlignment(Qt.AlignLeft)
        self.stack.addWidget(page)
        self.pages[name] = lay
        self._names.append(name)

    def _changed(self, i: int):
        self.stack.setCurrentIndex(i)
        if 0 <= i < len(self._names):
            self.tabChanged.emit(self._names[i])

    def set_current(self, name: str):
        self.bar.setCurrentIndex(self._names.index(name))

    # ---- buttons ---------------------------------------------------------------------------------------
    @staticmethod
    def large(text: str, ic: str, fn=None, checkable=False, tip: str | None = None, menu: list | None = None):
        b = QToolButton()
        b.setText(text.replace("&", "&&"))
        b.setIcon(icon(ic, 32))
        b.setIconSize(QSize(30, 30))
        b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        b.setFixedSize(max(54, min(120, 16 + b.fontMetrics().horizontalAdvance(text))), 66)
        b.setCheckable(checkable)
        if tip:
            b.setToolTip(tip)
        Ribbon._attach(b, fn, menu)
        return b

    @staticmethod
    def small(text: str, ic: str, fn=None, checkable=False, tip: str | None = None, menu: list | None = None):
        b = QToolButton()
        b.setText(text.replace("&", "&&"))
        b.setIcon(icon(ic, 16))
        b.setIconSize(QSize(16, 16))
        b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        b.setFixedHeight(22)
        b.setMinimumWidth(84)
        b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        b.setCheckable(checkable)
        if tip:
            b.setToolTip(tip)
        Ribbon._attach(b, fn, menu)
        return b

    @staticmethod
    def tiny(ic: str, tip: str, fn=None, checkable=False, size: int = 20):
        b = QToolButton()
        b.setIcon(icon(ic, size + 2))
        b.setIconSize(QSize(size, size))
        b.setFixedSize(size + 6, size + 6)
        b.setToolTip(tip)
        b.setCheckable(checkable)
        Ribbon._attach(b, fn, None)
        return b

    @staticmethod
    def _attach(b: QToolButton, fn, menu):
        if menu:
            m = QMenu(b)
            for text, f in menu:
                m.addAction(text, f)
            b.setMenu(m)
            b.setPopupMode(QToolButton.InstantPopup)
        elif fn:
            b.clicked.connect(lambda *_: fn())

    @staticmethod
    def stack_of(*buttons) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(1)
        for b in buttons:
            l.addWidget(b)
        l.addStretch(1)
        w.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)  # small buttons expand; the stack must not
        return w

    @staticmethod
    def grid_of(buttons, columns: int) -> QWidget:
        w = QWidget()
        g = QGridLayout(w)
        g.setContentsMargins(0, 2, 0, 0)
        g.setSpacing(1)
        for i, b in enumerate(buttons):
            g.addWidget(b, i // columns, i % columns)
        return w

    # ---- groups ---------------------------------------------------------------------------------------------
    def group(self, tab: str, title: str, widgets: list):
        box = QWidget()
        box.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        col = QVBoxLayout(box)
        col.setContentsMargins(4, 0, 4, 0)
        col.setSpacing(0)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)
        for w in widgets:
            row.addWidget(w, 0, Qt.AlignTop)
        col.addLayout(row, 1)
        lab = QLabel(title)
        lab.setAlignment(Qt.AlignCenter)
        lab.setStyleSheet("color:#777;font-size:10px;padding-bottom:1px")
        col.addWidget(lab)
        lay = self.pages[tab]
        lay.addWidget(box)
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("color:#d9d9d9")
        lay.addWidget(sep)

    def note(self, tab: str, text: str):
        lab = QLabel(text)
        lab.setStyleSheet("color:#888;padding:14px")
        self.pages[tab].addWidget(lab)

    # ---- Tell me ----------------------------------------------------------------------------------------------
    def register(self, label: str, fn):
        self._catalog[label] = fn
        self._completer_model.setStringList(sorted(self._catalog))

    def _run_catalog(self, text: str):
        fn = self._catalog.get(text) or next((f for k, f in self._catalog.items() if text.lower() in k.lower()), None)
        self.tellme.clear()
        if fn:
            fn()
