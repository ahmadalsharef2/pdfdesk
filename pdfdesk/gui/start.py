"""Start page: coloured sidebar (Home, Open File), Tool Wizard cards, Recent files list."""
from __future__ import annotations

import os
from datetime import datetime

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..lang import tr
from . import prefs, theme
from .icons import icon

MAX_RECENT = 20


def recent_files() -> list[str]:
    v = prefs.get("recent", [])
    return [p for p in (v if isinstance(v, list) else [v] if v else []) if p]


def add_recent(path: str):
    path = os.path.abspath(path)
    cur = [p for p in recent_files() if p != path]
    prefs.put("recent", [path] + cur[:MAX_RECENT - 1])


class Card(QFrame):
    clicked = Signal()

    def __init__(self, ic: str, title: str, text: str):
        super().__init__()
        self.setObjectName("card")
        self.setStyleSheet("#card{background:#fff;border:1px solid #e2e2e2;border-radius:4px}"
                           f"#card:hover{{border-color:{theme.ACCENT}}} #card QLabel{{background:transparent}}")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(215, 150)
        v = QVBoxLayout(self)
        top = QHBoxLayout()
        pic = QLabel()
        pic.setPixmap(icon(ic, 48).pixmap(QSize(48, 48)))
        top.addWidget(pic)
        t = QLabel(f"<b>{title}</b>")
        t.setStyleSheet("font-size:14px")
        top.addWidget(t, 1)
        v.addLayout(top)
        d = QLabel(text)
        d.setWordWrap(True)
        d.setStyleSheet(f"color:{theme.TEXT_MUTED}")
        v.addWidget(d, 1)
        use = QLabel(f'<a href="#" style="color:{theme.ACCENT};text-decoration:none">{tr("Use Now")}</a>')
        use.linkActivated.connect(lambda _: self.clicked.emit())
        v.addWidget(use)

    def mousePressEvent(self, e):
        self.clicked.emit()


class StartPage(QWidget):
    openFile = Signal(str)
    openDialog = Signal()
    action = Signal(str)       # 'edit' | 'create' | 'merge' | 'pages'

    def __init__(self):
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        side = QWidget()
        side.setObjectName("startSide")
        side.setFixedWidth(200)
        side.setStyleSheet(f"#startSide{{background:{theme.ACCENT}}} #startSide QLabel{{color:#fff;background:transparent}}")
        sv = QVBoxLayout(side)
        sv.setContentsMargins(0, 18, 0, 14)
        logo = QLabel("<span style='font-size:22px;font-weight:bold'>pdf</span>"
                      "<span style='font-size:22px'>desk</span>")
        logo.setContentsMargins(16, 0, 0, 14)
        sv.addWidget(logo)
        home = QLabel("  ⌂   " + tr("Home"))
        home.setStyleSheet(f"background:{theme.ACCENT_HOVER};padding:10px;font-size:14px;color:#fff")
        sv.addWidget(home)
        sv.addStretch(1)
        btn = QPushButton(tr("Open File"))
        btn.setStyleSheet("QPushButton{border:1px solid #fff;color:#fff;padding:8px;border-radius:3px;margin:0 12px}"
                          f"QPushButton:hover{{background:{theme.ACCENT_HOVER}}}")
        btn.clicked.connect(self.openDialog)
        sv.addWidget(btn)
        h.addWidget(side)

        body = QScrollArea()
        body.setWidgetResizable(True)
        body.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        inner.setObjectName("startInner")
        inner.setStyleSheet("#startInner{background:#f4f4f4}")
        iv = QVBoxLayout(inner)
        iv.setContentsMargins(18, 14, 18, 14)
        iv.addWidget(self._heading(tr("Tool Wizard"), " (" + tr("Frequently used tools") + ")"))
        cards = QHBoxLayout()
        for ic, title, text, act in (
                ("edit-text", tr("Edit PDF"), tr("Edit document and text format"), "edit"),
                ("create", tr("From File"), tr("Create a PDF from a Word, Excel, image or other file"), "create"),
                ("merge", tr("Merge PDF"), tr("Combine several files into one PDF"), "merge"),
                ("move-pages", tr("Move PDF Pages"), tr("Extract, delete, rotate and reorder pages"), "pages")):
            c = Card(ic, title, text)
            c.clicked.connect(lambda a=act: self.action.emit(a))
            cards.addWidget(c)
        cards.addStretch(1)
        iv.addLayout(cards)
        iv.addSpacing(10)
        iv.addWidget(self._heading(tr("Recent"), ""))
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels([tr("Name"), tr("Location"), tr("Date Modified")])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setMinimumHeight(260)
        self.tree.setColumnWidth(0, 300)
        self.tree.setColumnWidth(1, 440)
        self.tree.itemActivated.connect(lambda it, _c: self.openFile.emit(it.data(0, Qt.UserRole)))
        self.tree.itemDoubleClicked.connect(lambda it, _c: self.openFile.emit(it.data(0, Qt.UserRole)))
        iv.addWidget(self.tree, 1)
        body.setWidget(inner)
        h.addWidget(body, 1)
        self.refresh()

    @staticmethod
    def _heading(a: str, b: str) -> QLabel:
        return QLabel(f"<span style='font-size:18px;color:#333'>{a}</span><span style='color:#888'>{b}</span>")

    def refresh(self):
        self.tree.clear()
        for p in recent_files():
            if not os.path.exists(p):
                continue
            it = QTreeWidgetItem([os.path.basename(p), os.path.dirname(p),
                                  datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M")])
            it.setData(0, Qt.UserRole, p)
            it.setIcon(0, icon("pdfa", 20))
            self.tree.addTopLevelItem(it)
