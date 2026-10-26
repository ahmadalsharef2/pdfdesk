"""Continuous-scroll PDF view with interactive tools.

Pages render lazily into a small cache. Mouse tools turn gestures into ``toolAction`` dicts in PDF page
coordinates (unrotated page space, 1-based page numbers); the main window runs the matching command.
Undo/redo keeps whole-document snapshots, which also covers changes made by pikepdf or external tools.
"""
from __future__ import annotations

import pymupdf
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QKeySequence, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractScrollArea, QLineEdit

from ..commands import edit as edit_cmds
from ..commands import objects
from ..commands import search

RECT_TOOLS = {"select", "textbox", "rectangle", "oval", "area-highlight", "redact", "whiteout", "sign-place",
              "digital-sign", "stamp", "image", "link", "field-text", "field-check", "field-radio", "field-combo",
              "field-list", "field-button", "field-sign"}
LINE_TOOLS = {"line", "arrow", "callout"}
MARKUP_TOOLS = {"highlight", "underline", "strikeout", "squiggly", "replace-text"}
POINT_TOOLS = {"note", "file", "typewriter", "add-text", "insert-text"}
POLY_TOOLS = {"polygon", "cloud", "polyline"}
INK_TOOLS = {"pencil"}
CURSORS = {"hand": Qt.OpenHandCursor, "zoom": Qt.CrossCursor, "edit-text": Qt.IBeamCursor, "select": Qt.IBeamCursor,
           "edit-object": Qt.ArrowCursor}
# comments whose box is their whole shape, so dragging a corner can resize them
RESIZABLE_ANNOTS = {pymupdf.PDF_ANNOT_SQUARE, pymupdf.PDF_ANNOT_CIRCLE, pymupdf.PDF_ANNOT_FREE_TEXT,
                    pymupdf.PDF_ANNOT_STAMP}
HANDLE = 4                                                     # half size of a resize handle, in pixels


class DocView(QAbstractScrollArea):
    pageChanged = Signal(int)
    toolAction = Signal(dict)
    changed = Signal()

    GAP = 12
    UNDO_LIMIT = 30
    CACHE_BYTES = 256 * 2**20

    def __init__(self, doc: pymupdf.Document, path: str | None = None, password: str | None = None):
        super().__init__()
        self.doc, self.path, self.password = doc, path, password
        self.zoom = 1.0
        self.modified = False
        self.tool = "hand"
        self.undo_stack: list[tuple[str, bytes]] = []
        self.redo_stack: list[tuple[str, bytes]] = []
        self.highlights: dict[int, list[pymupdf.Rect]] = {}
        self.selected: tuple[int, int] | None = None          # (page index, annot xref)
        self.obj_sel: tuple[int, int] | None = None           # (page index, object number) for Edit Object
        self._drag: dict | None = None                         # moving or resizing the selection
        self._objs: dict[int, list] = {}                       # page index -> page objects, until the next edit
        self.text_sel: tuple[int, pymupdf.Rect] | None = None
        self._cache: dict[tuple, QImage] = {}
        self._press = None                                     # (page index, pdf point, view pos)
        self._cur = None                                       # current view pos while dragging
        self._pan = None
        self._poly: tuple[int, list] | None = None
        self._ink: tuple[int, list] | None = None
        self._hover_line = None
        self._editor: QLineEdit | None = None
        self._edit_target = None
        self.viewport().setStyleSheet("background:#6b6b6b")
        self.viewport().setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.relayout()

    # ---- document replacement and undo -----------------------------------------------------------
    def checkpoint(self, label: str):
        self.undo_stack.append((label, self.doc.tobytes()))
        if len(self.undo_stack) > self.UNDO_LIMIT:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def _open_bytes(self, data: bytes) -> pymupdf.Document:
        d = pymupdf.open("pdf", data)
        if d.needs_pass and self.password:
            d.authenticate(self.password)
        return d

    def replace_doc(self, doc: pymupdf.Document):
        self.doc = doc
        self.selected = self.obj_sel = None
        self.text_sel = None
        self.highlights.clear()
        self.after_edit()

    def undo(self) -> str | None:
        if not self.undo_stack:
            return None
        label, data = self.undo_stack.pop()
        self.redo_stack.append((label, self.doc.tobytes()))
        self.replace_doc(self._open_bytes(data))
        return label

    def redo(self) -> str | None:
        if not self.redo_stack:
            return None
        label, data = self.redo_stack.pop()
        self.undo_stack.append((label, self.doc.tobytes()))
        self.replace_doc(self._open_bytes(data))
        return label

    def rollback(self):
        """Undo the last checkpoint after a failed command, without offering it for redo."""
        if self.undo_stack:
            _label, data = self.undo_stack.pop()
            self.replace_doc(self._open_bytes(data))

    def after_edit(self):
        self.modified = True
        self.relayout()
        self.changed.emit()

    # ---- layout ------------------------------------------------------------------------------------
    def relayout(self):
        self._cache.clear()
        self._objs.clear()
        self.sizes = [(p.rect.width * self.zoom, p.rect.height * self.zoom) for p in self.doc]
        self.tops, y = [], self.GAP
        for _, h in self.sizes:
            self.tops.append(y)
            y += h + self.GAP
        self.total = y
        self.verticalScrollBar().setSingleStep(40)
        self._update_bars()
        self.viewport().update()

    def _update_bars(self):
        vp = self.viewport()
        self.verticalScrollBar().setRange(0, max(0, int(self.total - vp.height())))
        self.verticalScrollBar().setPageStep(vp.height())
        wmax = max((w for w, _ in self.sizes), default=0) + 2 * self.GAP
        self.horizontalScrollBar().setRange(0, max(0, int(wmax - vp.width())))
        self.horizontalScrollBar().setPageStep(vp.width())

    def resizeEvent(self, e):
        self._update_bars()

    def set_zoom(self, z: float):
        z = max(0.1, min(z, 8.0))
        page = self.current_page()
        self.zoom = z
        self.relayout()
        self.goto(page)

    def fit_width(self):
        if self.doc.page_count:
            widest = max(w for w, _ in self.sizes) / self.zoom
            self.set_zoom((self.viewport().width() - 2 * self.GAP - 4) / widest)

    def fit_page(self):
        if self.doc.page_count:
            r = self.doc[self.current_page()].rect
            self.set_zoom(min((self.viewport().width() - 2 * self.GAP) / r.width,
                              (self.viewport().height() - 2 * self.GAP) / r.height))

    def goto(self, page: int):
        if self.tops:
            self.verticalScrollBar().setValue(int(self.tops[max(0, min(page, len(self.tops) - 1))] - self.GAP))

    def current_page(self) -> int:
        mid = self.verticalScrollBar().value() + self.viewport().height() // 3
        n = 0
        for i, t in enumerate(self.tops):
            if t <= mid:
                n = i
        return n

    # ---- coordinates ------------------------------------------------------------------------------------
    def _origin(self, i: int) -> tuple[float, float]:
        w, _h = self.sizes[i]
        x = max(self.GAP, (self.viewport().width() - w) / 2) - self.horizontalScrollBar().value()
        return x, self.tops[i] - self.verticalScrollBar().value()

    def view_to_page(self, pos, clamp_page: int | None = None):
        """Viewport position -> (page index, unrotated PDF point). clamp_page keeps a drag on its page."""
        pages = [clamp_page] if clamp_page is not None else range(len(self.sizes))
        for i in pages:
            x, top = self._origin(i)
            w, h = self.sizes[i]
            if clamp_page is not None or (x <= pos.x() <= x + w and top <= pos.y() <= top + h):
                dx = min(max(pos.x() - x, 0), w) / self.zoom
                dy = min(max(pos.y() - top, 0), h) / self.zoom
                return i, pymupdf.Point(dx, dy) * self.doc[i].derotation_matrix
        return None, None

    def page_rect_to_view(self, i: int, rect) -> QRectF:
        r = pymupdf.Rect(rect) * self.doc[i].rotation_matrix
        x, top = self._origin(i)
        return QRectF(x + r.x0 * self.zoom, top + r.y0 * self.zoom, r.width * self.zoom, r.height * self.zoom)

    def page_point_to_view(self, i: int, pt) -> QPointF:
        p = pymupdf.Point(pt) * self.doc[i].rotation_matrix
        x, top = self._origin(i)
        return QPointF(x + p.x * self.zoom, top + p.y * self.zoom)

    # ---- painting -------------------------------------------------------------------------------------------
    def _render(self, i: int) -> QImage:
        key = (i, self.zoom, self.doc[i].rotation, id(self.doc))
        img = self._cache.get(key)
        if img is None:
            pm = self.doc[i].get_pixmap(matrix=pymupdf.Matrix(self.zoom, self.zoom), alpha=False)
            img = QImage(pm.samples, pm.width, pm.height, pm.stride, QImage.Format_RGB888).copy()
            # bound by bytes, not count: at high zoom a single page is tens of MB
            while self._cache and sum(c.sizeInBytes() for c in self._cache.values()) + img.sizeInBytes() > self.CACHE_BYTES:
                self._cache.pop(next(iter(self._cache)))
            self._cache[key] = img
        return img

    def paintEvent(self, _):
        p = QPainter(self.viewport())
        vh = self.viewport().height()
        for i in range(len(self.sizes)):
            x, top = self._origin(i)
            if top + self.sizes[i][1] < 0 or top > vh:
                continue
            p.drawImage(int(x), int(top), self._render(i))
            for r in self.highlights.get(i, []):
                p.fillRect(self.page_rect_to_view(i, r), QColor(255, 220, 0, 110))
        self._paint_overlays(p)
        p.end()
        self.pageChanged.emit(self.current_page())

    def _paint_overlays(self, p: QPainter):
        if self.text_sel:
            i, r = self.text_sel
            for w in self.doc[i].get_text("words"):
                if pymupdf.Rect(w[:4]).intersects(r):
                    p.fillRect(self.page_rect_to_view(i, w[:4]), QColor(40, 110, 255, 80))
        sel = self._selection()
        if sel:
            i, rect, resizable = sel
            if self._drag:
                rect = self._drag["rect"]
            r = self.page_rect_to_view(i, rect)
            p.setPen(QPen(QColor(30, 100, 255), 1.5, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(r.adjusted(-2, -2, 2, 2))
            if resizable:
                p.setPen(QPen(QColor(30, 100, 255), 1))
                p.setBrush(QColor(255, 255, 255))
                for c in (r.topLeft(), r.topRight(), r.bottomLeft(), r.bottomRight()):
                    p.drawRect(QRectF(c.x() - HANDLE, c.y() - HANDLE, 2 * HANDLE, 2 * HANDLE))
                p.setBrush(Qt.NoBrush)
        if self._hover_line is not None and self.tool == "edit-text" and self._editor is None:
            i, rect = self._hover_line
            p.setPen(QPen(QColor(30, 100, 255), 1))
            p.drawRect(self.page_rect_to_view(i, rect + (-1, -1, 1, 1)))
        pen = QPen(QColor(220, 30, 30), 1.2, Qt.DashLine)
        if self._press and self._cur is not None:
            i, start, _pos = self._press
            _j, cur = self.view_to_page(self._cur, clamp_page=i)
            p.setPen(pen)
            if self.tool in RECT_TOOLS:
                p.drawRect(self.page_rect_to_view(i, pymupdf.Rect(start, cur).normalize()))
            elif self.tool in LINE_TOOLS or self.tool in MARKUP_TOOLS:
                p.drawLine(self.page_point_to_view(i, start), self.page_point_to_view(i, cur))
        if self._poly:
            i, pts = self._poly
            p.setPen(QPen(QColor(220, 30, 30), 1.5))
            path = QPainterPath(self.page_point_to_view(i, pts[0]))
            for q in pts[1:]:
                path.lineTo(self.page_point_to_view(i, q))
            if self._cur is not None:
                path.lineTo(self._cur)
            p.drawPath(path)
        if self._ink:
            i, strokes = self._ink
            p.setPen(QPen(QColor(220, 30, 30), 1.8))
            for s in strokes:
                if len(s) > 1:
                    path = QPainterPath(self.page_point_to_view(i, s[0]))
                    for q in s[1:]:
                        path.lineTo(self.page_point_to_view(i, q))
                    p.drawPath(path)

    def scrollContentsBy(self, dx, dy):
        if self._editor is not None:
            self._commit_editor()
        self.viewport().update()

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            self.set_zoom(self.zoom * (1.1 if e.angleDelta().y() > 0 else 1 / 1.1))
        else:
            super().wheelEvent(e)

    # ---- tools ------------------------------------------------------------------------------------------------
    def set_tool(self, tool: str):
        self._commit_editor()
        self._press = self._poly = self._ink = self._drag = None
        if tool != "edit-object":
            self.obj_sel = None
        self.tool = tool
        self.viewport().setCursor(CURSORS.get(tool, Qt.CrossCursor))
        self.viewport().update()

    def _emit(self, **kw):
        self.toolAction.emit(kw)

    # ---- selection: comments (Hand) and page objects (Edit Object) ---------------------------------------
    def _selection(self):
        """(page index, rect, resizable) of the selected comment or object, or None."""
        if self.obj_sel:
            i, n = self.obj_sel
            o = next((o for o in self.page_objects(i) if o.index == n), None)
            return (i, o.rect, True) if o else None
        if self.selected:
            i, xref = self.selected
            page = self.doc[i]                  # keep the page alive while its annotations are used
            for a in page.annots() or []:
                if a.xref == xref:
                    return i, pymupdf.Rect(a.rect), a.type[0] in RESIZABLE_ANNOTS
        return None

    def _handle_at(self, pos):
        """Corner under the mouse ("tl", "tr", "bl", "br") of a resizable selection."""
        sel = self._selection()
        if not sel or not sel[2]:
            return None
        r = self.page_rect_to_view(sel[0], sel[1])
        for name, c in (("tl", r.topLeft()), ("tr", r.topRight()), ("bl", r.bottomLeft()), ("br", r.bottomRight())):
            if abs(pos.x() - c.x()) <= HANDLE + 2 and abs(pos.y() - c.y()) <= HANDLE + 2:
                return name
        return None

    def _start_drag(self, mode: str, pos, corner: str | None = None):
        i, rect, _ = self._selection()
        _j, pt = self.view_to_page(pos, clamp_page=i)
        self._drag = {"mode": mode, "corner": corner, "page": i, "start": pt, "orig": pymupdf.Rect(rect),
                      "rect": pymupdf.Rect(rect), "pos": pos, "keep_ratio": self.obj_sel is not None}

    def _update_drag(self, pos):
        d = self._drag
        _j, pt = self.view_to_page(pos, clamp_page=d["page"])
        o = d["orig"]
        if d["mode"] == "move":
            dx, dy = pt.x - d["start"].x, pt.y - d["start"].y
            d["rect"] = o + (dx, dy, dx, dy)
        else:
            # the opposite corner stays put
            fx, fy = (o.x1 if "l" in d["corner"] else o.x0), (o.y1 if "t" in d["corner"] else o.y0)
            w, h = max(abs(pt.x - fx), 4), max(abs(pt.y - fy), 4)
            if d["keep_ratio"] and o.width and o.height:
                k = max(w / o.width, h / o.height)
                w, h = o.width * k, o.height * k
            x0 = fx - w if "l" in d["corner"] else fx
            y0 = fy - h if "t" in d["corner"] else fy
            d["rect"] = pymupdf.Rect(x0, y0, x0 + w, y0 + h)
        self.viewport().update()

    def _finish_drag(self, pos):
        d, self._drag = self._drag, None
        moved = abs(pos.x() - d["pos"].x()) + abs(pos.y() - d["pos"].y()) > 3
        if not moved:
            self.viewport().update()
            return
        page = d["page"] + 1
        if self.obj_sel:
            self._emit(tool="object-rect", page=page, index=self.obj_sel[1], rect=d["rect"])
        elif d["mode"] == "move":
            o, r = d["orig"], d["rect"]
            self._emit(tool="move-annot", page=page, xref=self.selected[1], dx=r.x0 - o.x0, dy=r.y0 - o.y0)
        else:
            self._emit(tool="annot-rect", page=page, xref=self.selected[1], rect=d["rect"])

    def page_objects(self, i: int) -> list:
        if i not in self._objs:
            self._objs[i] = objects.list_objects(self.doc, i + 1)
        return self._objs[i]

    def _object_at(self, i: int, point):
        pt = pymupdf.Point(point)
        hits = [o for o in self.page_objects(i) if (o.rect + (-2, -2, 2, 2)).contains(pt)]
        return min(hits, key=lambda o: o.rect.get_area()) if hits else None

    def select_object_at(self, i: int, point) -> bool:
        o = self._object_at(i, point)
        self.obj_sel = (i, o.index) if o else None
        self.viewport().update()
        return o is not None

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return super().mousePressEvent(e)
        pos = e.position()
        i, pt = self.view_to_page(pos)
        self.setFocus()
        if self.tool in ("hand", "edit-object"):
            corner = self._handle_at(pos)
            if corner:
                self._start_drag("resize", pos, corner)
                return
        if self.tool == "edit-object":
            if i is not None and self.select_object_at(i, pt):
                self._start_drag("move", pos)
            return
        if self.tool == "hand":
            if i is not None:
                w = next((w for w in self.doc[i].widgets() if w.rect.contains(pt)), None)
                if w is not None:
                    self._emit(tool="fill-field", page=i + 1, xref=w.xref)
                    return
                from ..commands.comment import annot_at
                xref = annot_at(self.doc, i + 1, pt)
                self.selected = (i, xref) if xref else None
                if xref:
                    self._start_drag("move", pos)
                    self.viewport().update()
                    return
            self._pan = (pos, self.horizontalScrollBar().value(), self.verticalScrollBar().value())
            self.viewport().setCursor(Qt.ClosedHandCursor)
            self.viewport().update()
            return
        if i is None:
            return
        if self.tool == "zoom":
            self.set_zoom(self.zoom / 1.25 if e.modifiers() & Qt.ShiftModifier else self.zoom * 1.25)
            return
        if self.tool == "edit-text":
            self._commit_editor()           # clicking elsewhere keeps the edit, like Foxit
            ln = edit_cmds.line_at(self.doc, i + 1, pt)
            if ln:
                self._open_editor(i, ln)
            return
        if self.tool in POLY_TOOLS:
            if self._poly and self._poly[0] == i:
                self._poly[1].append(pt)
            else:
                self._poly = (i, [pt])
            self.viewport().update()
            return
        if self.tool in INK_TOOLS:
            if self._ink and self._ink[0] == i:
                self._ink[1].append([pt])
            else:
                self._ink = (i, [[pt]])
            self._press = (i, pt, pos)
            return
        self._press = (i, pt, pos)
        self._cur = pos

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self._drag:
            self._update_drag(pos)
            return
        if self.tool in ("hand", "edit-object") and not self._pan:
            corner = self._handle_at(pos)
            if corner:
                self.viewport().setCursor(Qt.SizeFDiagCursor if corner in ("tl", "br") else Qt.SizeBDiagCursor)
            else:
                self.viewport().setCursor(Qt.SizeAllCursor if self.tool == "edit-object" and self._over_object(pos)
                                          else CURSORS.get(self.tool, Qt.CrossCursor))
        if self._pan:
            start, hx, vy = self._pan
            self.horizontalScrollBar().setValue(int(hx - (pos.x() - start.x())))
            self.verticalScrollBar().setValue(int(vy - (pos.y() - start.y())))
            return
        if self.tool == "edit-text" and self._editor is None:
            i, pt = self.view_to_page(pos)
            ln = edit_cmds.line_at(self.doc, i + 1, pt) if i is not None else None
            new = (i, ln.rect) if ln else None
            if new != self._hover_line:
                self._hover_line = new
                self.viewport().update()
            return
        if self._ink and self._press and e.buttons() & Qt.LeftButton:
            i = self._ink[0]
            _j, pt = self.view_to_page(pos, clamp_page=i)
            self._ink[1][-1].append(pt)
            self.viewport().update()
            return
        self._cur = pos
        if self._press or self._poly:
            self.viewport().update()

    def _over_object(self, pos) -> bool:
        i, pt = self.view_to_page(pos)
        return i is not None and self._object_at(i, pt) is not None

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        pos = e.position()
        if self._drag:
            self._finish_drag(pos)
            return
        if self._pan:
            self._pan = None
            self.viewport().setCursor(CURSORS.get(self.tool, Qt.CrossCursor))
            return
        if not self._press:
            return
        i, start, spos = self._press
        _j, end = self.view_to_page(pos, clamp_page=i)
        moved = abs(pos.x() - spos.x()) + abs(pos.y() - spos.y()) > 4
        self._press, self._cur = None, None
        page = i + 1
        t = self.tool
        if t in INK_TOOLS:
            pass  # strokes collect until the user presses Enter or switches tool
        elif t == "select":
            self.text_sel = (i, pymupdf.Rect(start, end).normalize()) if moved else None
        elif t in RECT_TOOLS:
            self._emit(tool=t, page=page, point=start, rect=pymupdf.Rect(start, end).normalize() if moved else None)
        elif t in LINE_TOOLS:
            if moved:
                self._emit(tool=t, page=page, start=start, stop=end)
        elif t in MARKUP_TOOLS:
            if moved:
                self._emit(tool=t, page=page, start=start, stop=end)
        elif t in POINT_TOOLS:
            self._emit(tool=t, page=page, point=start)
        self.viewport().update()

    def mouseDoubleClickEvent(self, e):
        if self.tool in POLY_TOOLS and self._poly:
            self.finish_shape()
            return
        if self.tool == "hand" and self.selected:
            i, xref = self.selected
            self._emit(tool="edit-annot", page=i + 1, xref=xref)

    def finish_shape(self):
        if self._poly:
            i, pts = self._poly
            self._poly = None
            if len(pts) >= 2:
                self._emit(tool=self.tool, page=i + 1, points=pts)
        if self._ink:
            i, strokes = self._ink
            self._ink = None
            strokes = [s for s in strokes if len(s) > 1]
            if strokes:
                self._emit(tool=self.tool, page=i + 1, strokes=strokes)
        self.viewport().update()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.obj_sel:
            i, n = self.obj_sel
            self.obj_sel = None
            self._emit(tool="delete-object", page=i + 1, index=n)
            return
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.selected:
            i, xref = self.selected
            self.selected = None
            self._emit(tool="delete-annot", page=i + 1, xref=xref)
            return
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and (self._poly or self._ink):
            self.finish_shape()
            return
        if e.key() == Qt.Key_Escape:
            self._poly = self._ink = self._press = self._drag = None
            self.selected = self.text_sel = self.obj_sel = None
            self.viewport().update()
            return
        if e.matches(QKeySequence.StandardKey.Copy) and self.text_sel:
            QGuiApplication.clipboard().setText(self.selected_text())
            return
        super().keyPressEvent(e)

    def selected_text(self) -> str:
        if not self.text_sel:
            return ""
        i, r = self.text_sel
        return self.doc[i].get_textbox(r).strip()

    # ---- inline text editor (Edit Text tool) -------------------------------------------------------------
    def _open_editor(self, i: int, ln):
        self._commit_editor()
        ed = QLineEdit(self.viewport())
        ed.setText(ln.text)
        f = QFont()
        f.setPixelSize(max(8, int(ln.size * self.zoom * 0.95)))
        ed.setFont(f)
        r = self.page_rect_to_view(i, ln.rect)
        ed.setGeometry(int(r.x()) - 2, int(r.y()) - 2, max(int(r.width()) + 60, 120), int(r.height()) + 6)
        ed.setStyleSheet("background:#fffbe6;border:1px solid #1e64ff;")
        ed.editingFinished.connect(self._commit_editor)     # Enter or focus moving away; Esc cancels
        ed.show()
        ed.setFocus()
        ed.selectAll()
        self._editor, self._edit_target = ed, (i, ln)
        ed.installEventFilter(self)

    def eventFilter(self, obj, ev):
        if obj is self._editor and ev.type() == ev.Type.KeyPress and ev.key() == Qt.Key_Escape:
            self._close_editor()
            return True
        return super().eventFilter(obj, ev)

    def _commit_editor(self):
        if self._editor is None:
            return
        text = self._editor.text()
        i, ln = self._edit_target
        self._close_editor()
        if text != ln.text:
            center = ln.rect.tl + (ln.rect.br - ln.rect.tl) / 2
            self._emit(tool="edit-text-commit", page=i + 1, point=center, text=text)

    def _close_editor(self):
        if self._editor is not None:
            ed, self._editor = self._editor, None
            ed.hide()
            ed.deleteLater()
            self._edit_target = None
            self._hover_line = None
            self.setFocus()

    # ---- search ----------------------------------------------------------------------------------------------
    def find(self, text: str) -> int:
        self.highlights.clear()
        total = 0
        for i, p in enumerate(self.doc):
            rs = search.find(p, text) if text else []
            if rs:
                self.highlights[i] = rs
                total += len(rs)
        if self.highlights:
            self.goto(min(self.highlights))
        self.viewport().update()
        return total

