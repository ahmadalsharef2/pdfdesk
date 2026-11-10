"""Navigation panels: page thumbnails (drag to reorder), bookmarks, comments."""
from __future__ import annotations

import pymupdf
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QTreeWidget,
    QTreeWidgetItem,
)

from ..lang import tr

ROLE = Qt.UserRole


class Thumbnails(QListWidget):
    """Page thumbnails. Drag pages to reorder; right-click for page commands."""
    reordered = Signal(list)          # new order of 0-based page indexes
    pageCommand = Signal(str, list)   # command name, 0-based selected pages
    activated_page = Signal(int)

    THUMB_W = 110

    def __init__(self):
        super().__init__()
        self.setViewMode(QListWidget.IconMode)      # page above its number, one column
        self.setFlow(QListWidget.TopToBottom)
        self.setWrapping(False)
        self.setMovement(QListWidget.Snap)
        self.setResizeMode(QListWidget.Adjust)
        self.setUniformItemSizes(True)
        self.setIconSize(QSize(self.THUMB_W, int(self.THUMB_W * 1.42)))
        self.setGridSize(QSize(self.THUMB_W + 24, int(self.THUMB_W * 1.42) + 30))
        self.setSpacing(2)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.itemClicked.connect(lambda it: self.activated_page.emit(it.data(ROLE)))
        self.model().rowsMoved.connect(self._moved)
        self._doc = None
        self._todo: list[int] = []
        self._timer = QTimer(self, interval=0)
        self._timer.timeout.connect(self._render_some)

    def set_document(self, doc: pymupdf.Document | None):
        self._doc = doc
        self._timer.stop()
        self.blockSignals(True)
        self.clear()
        if doc is None:
            self.blockSignals(False)
            return
        blank = QPixmap(self.iconSize())
        blank.fill(Qt.white)
        for i in range(doc.page_count):
            label = doc[i].get_label() if i < 2000 else ""
            it = QListWidgetItem(QIcon(blank), label or str(i + 1))
            it.setData(ROLE, i)
            it.setTextAlignment(Qt.AlignCenter)
            self.addItem(it)
        self.blockSignals(False)
        self._todo = list(range(doc.page_count))
        self._timer.start()

    def _render_some(self):
        if not self._todo or self._doc is None:
            self._timer.stop()
            return
        # visible items first
        first = self.indexAt(self.viewport().rect().topLeft()).row()
        if first >= 0:
            vis = [i for i in range(first, first + 12) if i in self._todo]
            for i in vis:
                self._todo.remove(i)
                self._todo.insert(0, i)
        for _ in range(4):
            if not self._todo:
                break
            i = self._todo.pop(0)
            if i >= self._doc.page_count:
                continue
            p = self._doc[i]
            dpr = self.devicePixelRatioF()
            z = self.THUMB_W / max(p.rect.width, p.rect.height) * dpr
            pm = p.get_pixmap(matrix=pymupdf.Matrix(z, z), alpha=False)
            img = QImage(pm.samples, pm.width, pm.height, pm.stride, QImage.Format_RGB888).copy()
            img.setDevicePixelRatio(dpr)
            it = self.item(i)
            if it is not None:
                it.setIcon(QIcon(QPixmap.fromImage(img)))

    def _moved(self, *_):
        order = [self.item(r).data(ROLE) for r in range(self.count())]
        if order != sorted(order):
            QTimer.singleShot(0, lambda: self.reordered.emit(order))

    def follow(self, page: int):
        """Show the page the document view is on, unless the user is working in the panel."""
        if self.hasFocus() or not 0 <= page < self.count() or self.currentRow() == page:
            return
        self.blockSignals(True)
        self.setCurrentRow(page)
        self.blockSignals(False)
        self.scrollToItem(self.item(page))

    def selected_pages(self) -> list[int]:
        return sorted(it.data(ROLE) for it in self.selectedItems())

    def _menu(self, pos):
        if self.itemAt(pos) is None:
            return
        m = QMenu(self)
        for label, name in ((tr("Rotate right"), "rotate-right"), (tr("Rotate left"), "rotate-left"),
                            (tr("Delete"), "delete"), (tr("Extract…"), "extract"), (tr("Duplicate"), "duplicate"),
                            (tr("Insert blank page after"), "insert-blank"),
                            (tr("Insert from file after…"), "insert-file")):
            m.addAction(label, lambda n=name: self.pageCommand.emit(n, self.selected_pages()))
        m.exec(self.mapToGlobal(pos))


class Bookmarks(QTreeWidget):
    """Bookmark tree; right-click to add, rename, delete or change level (the app runs the command)."""
    activated_page = Signal(int)
    command = Signal(str, int)  # command name, index into the outline (-1: none selected)

    def __init__(self):
        super().__init__()
        self.setHeaderHidden(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.itemClicked.connect(lambda it, _c: it.data(0, ROLE) is not None and
                                 self.activated_page.emit(it.data(0, ROLE)))

    def set_document(self, doc):
        self.clear()
        if doc is None:
            return
        parents = {0: self.invisibleRootItem()}
        for k, (lvl, title, page, *_) in enumerate(doc.get_toc()):
            parent = parents.get(lvl - 1, self.invisibleRootItem())
            it = QTreeWidgetItem(parent, [title])
            it.setData(0, ROLE, max(0, page - 1))
            it.setData(0, ROLE + 1, k)
            parents[lvl] = it
        self.expandToDepth(0)

    def _menu(self, pos):
        it = self.itemAt(pos)
        k = it.data(0, ROLE + 1) if it is not None else -1
        m = QMenu(self)
        m.addAction(tr("Add bookmark here…"), lambda: self.command.emit("add", k))
        if it is not None:
            m.addAction(tr("Add child bookmark…"), lambda: self.command.emit("add-child", k))
            m.addAction(tr("Rename…"), lambda: self.command.emit("rename", k))
            m.addAction(tr("Set to current page"), lambda: self.command.emit("set-page", k))
            m.addAction(tr("Promote"), lambda: self.command.emit("promote", k))
            m.addAction(tr("Demote"), lambda: self.command.emit("demote", k))
            m.addAction(tr("Delete"), lambda: self.command.emit("delete", k))
        m.addSeparator()
        m.addAction(tr("Create from headings"), lambda: self.command.emit("from-headings", k))
        m.exec(self.viewport().mapToGlobal(pos))


class Comments(QListWidget):
    """Comments of the document; click to show one, double-click or right-click to change or delete it."""
    activated = Signal(int, int)  # page index, xref
    command = Signal(str, int, int)  # "properties" or "delete", page index, xref

    def __init__(self):
        super().__init__()
        self.itemClicked.connect(lambda it: self.activated.emit(*it.data(ROLE)))
        self.itemDoubleClicked.connect(lambda it: self.command.emit("properties", *it.data(ROLE)))
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

    def _menu(self, pos):
        it = self.itemAt(pos)
        if it is None:
            return
        m = QMenu(self)
        m.addAction(tr("Go to"), lambda: self.activated.emit(*it.data(ROLE)))
        m.addAction(tr("Properties…"), lambda: self.command.emit("properties", *it.data(ROLE)))
        m.addAction(tr("Reply…"), lambda: self.command.emit("reply", *it.data(ROLE)))
        st = m.addMenu(tr("Set Status"))
        for s in ("Accepted", "Rejected", "Cancelled", "Completed", "None"):
            st.addAction(tr(s), lambda s=s: self.command.emit("status:" + s, *it.data(ROLE)))
        m.addSeparator()
        m.addAction(tr("Delete"), lambda: self.command.emit("delete", *it.data(ROLE)))
        m.exec(self.viewport().mapToGlobal(pos))

    def set_document(self, doc):
        self.clear()
        if doc is None:
            return
        from ..commands import run
        items = run("Comment.List", doc)
        replies: dict[int, list] = {}
        for c in items:
            if c["reply_to"]:
                replies.setdefault(c["reply_to"], []).append(c)

        def add(c, depth):
            text = c["content"].replace("\n", " ")
            state = f"  [{c['state']}]" if c["state"] else ""
            head = ("    ↳ " * depth) + (f"{c['author']}" if depth else f"p.{c['page']}  {c['type']}  {c['author']}")
            it = QListWidgetItem(f"{head}{state}\n{'      ' * depth}{text[:80]}")
            it.setData(ROLE, (c["page"] - 1, c["xref"]))
            self.addItem(it)
            for r in replies.get(c["xref"], []):
                add(r, depth + 1)
        for c in items:
            if not c["reply_to"]:
                add(c, 0)
