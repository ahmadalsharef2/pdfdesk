"""Continuous-scroll PDF view with interactive tools.

Pages render lazily into a small cache. Mouse tools turn gestures into ``toolAction`` dicts in PDF page
coordinates (unrotated page space, 1-based page numbers); the main window runs the matching command.
Undo/redo keeps whole-document snapshots, which also covers changes made by pikepdf or external tools.
"""
from __future__ import annotations

import time
import uuid

import pymupdf
from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QDesktopServices,
    QGuiApplication,
    QImage,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QAbstractScrollArea, QMenu

from ..commands import edit as edit_cmds
from ..commands import objects, search
from ..commands.comment import DEFAULT_COLORS, annot_at, text_between
from ..commands.comment import style as comment_style
from ..lang import tr
from . import clipboard, prefs
from .dialogs import fill_color_menu, qcolor, swatch
from .text_editor import InlineFieldEditor, InlineTextEditor

RECT_TOOLS = {"textbox", "rectangle", "oval", "area-highlight", "redact", "whiteout", "sign-place",
              "digital-sign", "stamp", "image", "link", "field-text", "field-check", "field-radio", "field-combo",
              "field-list", "field-button", "field-sign"}
LINE_TOOLS = {"line", "arrow", "callout"}
MARKUP_TOOLS = {"highlight", "underline", "strikeout", "squiggly", "replace-text"}
TEXT_TOOLS = MARKUP_TOOLS | {"select"}                         # drag selects along the text flow
SEL_COLORS = {"select": QColor(40, 110, 255, 80), "highlight": QColor(255, 220, 0, 110),
              "underline": QColor(0, 160, 0, 70), "strikeout": QColor(230, 30, 30, 70),
              "squiggly": QColor(30, 80, 230, 70), "replace-text": QColor(230, 30, 30, 70)}
POINT_TOOLS = {"note", "file", "typewriter", "add-text", "insert-text"}
POLY_TOOLS = {"polygon", "cloud", "polyline"}
INK_TOOLS = {"pencil"}
CURSORS = {"hand": Qt.OpenHandCursor, "zoom": Qt.CrossCursor, "edit-text": Qt.IBeamCursor,
           "edit-object": Qt.ArrowCursor, **{t: Qt.IBeamCursor for t in TEXT_TOOLS}}
# comments whose box is their whole shape, so dragging a corner can resize them
RESIZABLE_ANNOTS = {pymupdf.PDF_ANNOT_SQUARE, pymupdf.PDF_ANNOT_CIRCLE, pymupdf.PDF_ANNOT_FREE_TEXT,
                    pymupdf.PDF_ANNOT_STAMP}
# comment type -> the tool that makes it, for "Use as Default Color"
ANNOT_TOOLS = {"Highlight": "highlight", "Underline": "underline", "StrikeOut": "strikeout", "Squiggly": "squiggly",
               "Text": "note", "FreeText": "typewriter", "Square": "rectangle", "Circle": "oval", "Line": "line",
               "Polygon": "polygon", "PolyLine": "polyline", "Ink": "pencil"}
HANDLE = 4                                                     # half size of a resize handle, in pixels
TYPED_TOOLS = {"typewriter", "add-text", "note"}               # click, then type on the page
FILLABLE = {pymupdf.PDF_WIDGET_TYPE_TEXT: "text", pymupdf.PDF_WIDGET_TYPE_COMBOBOX: "combo",
            pymupdf.PDF_WIDGET_TYPE_LISTBOX: "list"}
TOGGLES = {pymupdf.PDF_WIDGET_TYPE_CHECKBOX, pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON, pymupdf.PDF_WIDGET_TYPE_BUTTON}
NO_TEXT_HINT = "This page has no text layer (a scan). Run Convert > OCR to select, mark or edit its text."
ARROWS = {Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0), Qt.Key_Up: (0, -1), Qt.Key_Down: (0, 1)}


class DocView(QAbstractScrollArea):
    pageChanged = Signal(int)
    toolAction = Signal(dict)
    changed = Signal()

    GAP = 12
    UNDO_LIMIT = 30
    UNDO_BYTES = 768 * 2**20            # a big scan would otherwise keep 30 whole copies in memory
    CACHE_BYTES = 256 * 2**20

    def __init__(self, doc: pymupdf.Document, path: str | None = None, password: str | None = None):
        super().__init__()
        self.doc, self.path, self.password = doc, path, password
        self.new_name: str | None = None                       # a new document's name until it is saved
        self.security = None                                   # core.security state, kept across saves
        self.readonly = False                                  # opened with the user password only
        self.zoom = 1.0
        self.fit_mode: str | None = None                       # "width" | "page": kept through resizes
        self.page_sizes: list[tuple[float, float]] = []
        self.modified = False
        self.tool = "hand"
        self.tool_colors: dict[str, tuple] = {}               # the window's color choices, shared by all views
        self.token = uuid.uuid4().hex                          # names this document on the clipboard
        self.undo_stack: list[tuple[str, bytes]] = []
        self.redo_stack: list[tuple[str, bytes]] = []
        self.highlights: dict[int, list[pymupdf.Rect]] = {}
        self.hits: list[tuple[int, pymupdf.Rect]] = []       # search hits in reading order
        self.hit = -1                                          # the current one
        self.find_text = ""
        self.selected: tuple[int, int] | None = None          # (page index, annot xref)
        self.obj_sel: tuple[int, int] | None = None           # (page index, object number) for Edit Object
        self._drag: dict | None = None                         # moving or resizing the selection
        self._objs: dict[int, list] = {}                       # page index -> page objects, until the next edit
        self._hit_cache: dict[int, tuple] = {}                 # page index -> (fields, comments, links) for hovering
        self.text_sel: tuple[int, pymupdf.Point, pymupdf.Point] | None = None     # page index, start, stop
        self._words: dict[int, list] = {}                      # page index -> words, until the next edit
        self._cache: dict[tuple, QImage] = {}
        self._press = None                                     # (page index, pdf point, view pos)
        self._cur = None                                       # current view pos while dragging
        self._pan = None
        self._poly: tuple[int, list] | None = None
        self._ink: tuple[int, list] | None = None
        self._hover_line = None
        self._announced = None
        self._editor: InlineTextEditor | InlineFieldEditor | None = None
        self._edit_target: dict | None = None                  # what the open editor changes; see _commit_editor
        self._last_checkpoint = 0.0
        self._link_press = None                                # a link under the Hand when the button went down
        self._hover_link = None
        self._back: list[tuple[int, int]] = []                 # scroll positions before following links (Alt+Left)
        self.viewport().setStyleSheet("background:#6b6b6b")
        self.viewport().setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.relayout()

    # ---- document replacement and undo -----------------------------------------------------------
    MERGE_S = 0.8                               # arrow-key moves this close together are one undo step

    def checkpoint(self, label: str):
        now = time.monotonic()
        merge = (self.undo_stack and label == self.undo_stack[-1][0] and now - self._last_checkpoint < self.MERGE_S
                 and label in (tr("Nudge object"), tr("Nudge comment")))
        self._last_checkpoint = now
        if merge:
            self.redo_stack.clear()
            return
        self.undo_stack.append((label, self.doc.tobytes()))
        while len(self.undo_stack) > self.UNDO_LIMIT or (
                len(self.undo_stack) > 2 and sum(len(d) for _l, d in self.undo_stack) > self.UNDO_BYTES):
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
        self.hits, self.hit, self.find_text = [], -1, ""
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
        """The document changed: forget everything derived from its pages and lay them out again."""
        self._cache.clear()
        self._objs.clear()
        self._words.clear()
        self._hit_cache.clear()
        self.page_sizes = [(p.rect.width, p.rect.height) for p in self.doc]     # in points, as displayed (rotated)
        self._layout()
        if self.fit_mode and not self._fit():
            return                                   # _fit laid out again at the fitted zoom
        self.verticalScrollBar().setSingleStep(40)
        self._update_bars()
        self._announce()
        self.viewport().update()

    def _layout(self):
        """Page positions at the current zoom; page_sizes must be current."""
        self.sizes = [(w * self.zoom, h * self.zoom) for w, h in self.page_sizes]
        self.tops, y = [], self.GAP
        for _, h in self.sizes:
            self.tops.append(y)
            y += h + self.GAP
        self.total = y

    def _update_bars(self):
        vp = self.viewport()
        self.verticalScrollBar().setRange(0, max(0, int(self.total - vp.height())))
        self.verticalScrollBar().setPageStep(vp.height())
        wmax = max((w for w, _ in self.sizes), default=0) + 2 * self.GAP
        self.horizontalScrollBar().setRange(0, max(0, int(wmax - vp.width())))
        self.horizontalScrollBar().setPageStep(vp.width())

    def resizeEvent(self, e):
        """The view got another size (window resized or maximized, panel shown, scrollbar appeared): keep a
        fitted zoom fitted, and keep the open text editor over its line (pages are centred, so they move)."""
        super().resizeEvent(e)
        if not (self.fit_mode and self._fit()):
            self._update_bars()
        self._place_editor()

    def _place_editor(self):
        if self._editor is not None:
            t = self._edit_target
            self._editor.place(self.page_rect_to_view(t["page"], t["rect"]))

    def set_zoom(self, z: float, anchor=None, fit: str | None = None):
        """Zoom so that the document point under `anchor` (a viewport position; default: the centre, or the top
        when the view is at the top) stays where it is. An explicit zoom ends Fit Width / Fit Page."""
        self._commit_editor()                   # its font size follows the zoom it was opened at
        z = max(0.1, min(z, 8.0))
        self.fit_mode = fit
        if abs(z - self.zoom) < 1e-9:
            return False
        vp = self.viewport()
        if anchor is None:
            at_top = self.verticalScrollBar().value() == 0
            anchor = QPointF(vp.width() / 2, 0 if at_top else vp.height() / 2)
        # where the anchor is in the document, in page units, before the zoom changes
        vy = self.verticalScrollBar().value() + anchor.y()
        i = max((k for k, t in enumerate(self.tops) if t <= vy), default=0)
        dy = vy - self.tops[i] if self.tops else 0.0
        in_page = self.sizes[i][1] >= dy >= 0 if self.sizes else False
        ox, _ = self._origin(i) if self.sizes else (0, 0)
        px = (anchor.x() - ox) / self.zoom
        old = self.zoom
        self.zoom = z
        self._layout()
        self._update_bars()
        if self.tops:
            top = self.tops[i] + (dy * z / old if in_page else dy)         # a gap between pages is not scaled
            self.verticalScrollBar().setValue(int(round(top - anchor.y())))
            w = self.sizes[i][0]
            left = max(self.GAP, (vp.width() - w) / 2) + px * z           # page origin with no horizontal scroll
            self.horizontalScrollBar().setValue(int(round(left - anchor.x())))
        self._cache.clear()
        self._announce()
        self.viewport().update()
        return True

    def _fit(self) -> bool:
        """Re-apply the current fit mode. True when the zoom changed (and the view is laid out again)."""
        z = self.fit_zoom(self.fit_mode)
        return z is not None and self.set_zoom(z, fit=self.fit_mode)

    def fit_zoom(self, mode: str) -> float | None:
        """The zoom Fit Width or Fit Page needs. Measured on the viewport without scrollbars, then with the
        vertical one when the pages will need it: the zoom must not depend on which bars happen to show."""
        if not self.doc.page_count or not self.page_sizes:
            return None
        full = self.maximumViewportSize()
        bar = self.verticalScrollBar().sizeHint().width() if self.verticalScrollBarPolicy() != Qt.ScrollBarAlwaysOff else 0
        if self.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOn:
            full = QSize(full.width() - bar, full.height())
            bar = 0

        def zoom_for(width: float) -> float:
            if mode == "page":
                w, h = self.page_sizes[min(self.current_page(), len(self.page_sizes) - 1)]
                return min((width - 2 * self.GAP) / w, (full.height() - 2 * self.GAP) / h)
            widest = max(w for w, _ in self.page_sizes)
            return (width - 2 * self.GAP - 4) / widest

        z = zoom_for(full.width())
        if bar and sum(h * z + self.GAP for _, h in self.page_sizes) + self.GAP > full.height():
            z = zoom_for(full.width() - bar)
        return max(0.1, min(z, 8.0))

    def fit_width(self):
        self.fit_mode = "width"
        self._fit()

    def fit_page(self):
        self.fit_mode = "page"
        self._fit()

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
        dpr = self.viewport().devicePixelRatioF()              # render at the screen's real resolution
        key = (i, self.zoom, dpr, self.doc[i].rotation, id(self.doc))
        img = self._cache.get(key)
        if img is None:
            k = self.zoom * dpr
            pm = self.doc[i].get_pixmap(matrix=pymupdf.Matrix(k, k), alpha=False)
            img = QImage(pm.samples, pm.width, pm.height, pm.stride, QImage.Format_RGB888).copy()
            img.setDevicePixelRatio(dpr)
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
            if 0 <= self.hit < len(self.hits) and self.hits[self.hit][0] == i:      # the current hit stands out
                r = self.page_rect_to_view(i, self.hits[self.hit][1]).adjusted(-2, -2, 2, 2)
                p.fillRect(r, QColor(255, 140, 0, 120))
                p.setPen(QPen(QColor(230, 90, 0), 1.5))
                p.drawRect(r)
        self._paint_overlays(p)
        p.end()

    def _announce(self):
        """Tell the window the current page, only when it or the zoom changed. Never from paintEvent: the
        status bar update repaints the window, which repainted this view, in a loop."""
        now = (self.current_page(), self.zoom, len(self.sizes))
        if now != self._announced:
            self._announced = now
            self.pageChanged.emit(now[0])

    def _paint_overlays(self, p: QPainter):
        t = self._edit_target
        if self._editor is not None and t["kind"] in ("line", "annot"):
            # the text being edited is hidden, so its old glyphs do not show around the editor
            p.fillRect(self.page_rect_to_view(t["page"], t["rect"]).adjusted(-2, -2, 2, 2), QColor("#fffbe6"))
        if self.text_sel:
            i, a, b = self.text_sel
            for r, _t in self._text_between(i, a, b):
                p.fillRect(self.page_rect_to_view(i, r), SEL_COLORS["select"])
        sel = self._selection()
        if sel:
            i, rect, resizable = sel
            if self._drag:
                i, rect = self._drag["page_to"], self._drag["rect"]
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
            elif self.tool in TEXT_TOOLS:
                for r, _t in self._text_between(i, start, cur):
                    p.fillRect(self.page_rect_to_view(i, r), self._preview(self.tool))
            elif self.tool in LINE_TOOLS:
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
        self._place_editor()                    # the editor moves with its text; scrolling does not end the edit
        self._announce()
        self.viewport().update()

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:                  # zoom about the mouse
            self.set_zoom(self.zoom * (1.1 if e.angleDelta().y() > 0 else 1 / 1.1), anchor=e.position())
        else:
            super().wheelEvent(e)

    # ---- tools ------------------------------------------------------------------------------------------------
    def set_tool(self, tool: str):
        self._commit_editor()
        self._press = self._poly = self._ink = self._drag = None
        if tool not in ("edit-object", "hand"):               # both tools work with a selected object
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

    def _start_drag(self, mode: str, pos, corner: str | None = None, shift: bool = False):
        i, rect, _ = self._selection()
        _j, pt = self.view_to_page(pos, clamp_page=i)
        keep = False
        if self.obj_sel:
            o = next((o for o in self.page_objects(i) if o.index == self.obj_sel[1]), None)
            keep = o is not None and o.kind != "path"            # images and text keep their proportions
        self._drag = {"mode": mode, "corner": corner, "page": i, "page_to": i, "start": pt,
                      "orig": pymupdf.Rect(rect), "rect": pymupdf.Rect(rect), "pos": pos,
                      "keep_ratio": keep != shift}

    def _update_drag(self, pos):
        d = self._drag
        o = d["orig"]
        if d["mode"] == "move":
            j, pt = self.view_to_page(pos)                      # a move may end on another page
            if j is None:
                pass                                            # between pages: keep the last position
            elif j != d["page"]:
                d["page_to"] = j
                tl = pt - (d["start"] - o.tl)                   # the grabbed point keeps its place in the box
                d["rect"] = pymupdf.Rect(tl, tl + (o.width, o.height))
            else:
                d["page_to"] = j
                _j, pt = self.view_to_page(pos, clamp_page=j)
                dx, dy = pt.x - d["start"].x, pt.y - d["start"].y
                d["rect"] = o + (dx, dy, dx, dy)
        else:
            _j, pt = self.view_to_page(pos, clamp_page=d["page"])
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
        if d["mode"] == "move" and d["page_to"] != d["page"]:
            to = d["page_to"] + 1
            if self.obj_sel:
                self._emit(tool="object-to-page", page=page, index=self.obj_sel[1], to_page=to, rect=d["rect"])
            else:
                self._emit(tool="annot-to-page", page=page, xref=self.selected[1], to_page=to, rect=d["rect"])
        elif self.obj_sel:
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

    def _object_at(self, i: int, point, added_only: bool = False):
        """The smallest object under point; added_only: only what pdfdesk placed (text, images, signatures)."""
        pt = pymupdf.Point(point)
        hits = [o for o in self.page_objects(i) if (o.added or not added_only) and (o.rect + (-2, -2, 2, 2)).contains(pt)]
        return min(hits, key=lambda o: o.rect.get_area()) if hits else None

    def select_object_at(self, i: int, point, added_only: bool = False) -> bool:
        o = self._object_at(i, point, added_only)
        self.obj_sel = (i, o.index) if o else None
        if o:
            self.selected = None
        self.viewport().update()
        return o is not None

    def select_last_object(self, i: int):
        """Select the object drawn last on a page: what was just pasted or placed."""
        objs = self.page_objects(i)
        self.obj_sel = (i, objs[-1].index) if objs else None
        self.selected = None
        self.viewport().update()

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return super().mousePressEvent(e)
        if self._editor is not None:            # a click elsewhere ends the edit and keeps it
            kind = self._edit_target["kind"]
            self._commit_editor()
            if kind == "new":                   # it only finishes the new text; the next click starts another
                return
        pos = e.position()
        i, pt = self.view_to_page(pos)
        self.setFocus()
        if self.tool in ("hand", "edit-object"):
            corner = self._handle_at(pos)
            if corner:
                self._start_drag("resize", pos, corner, bool(e.modifiers() & Qt.ShiftModifier))
                return
        if self.tool == "edit-object":
            if i is not None and self.select_object_at(i, pt):
                self._start_drag("move", pos)
            return
        if self.tool == "hand":
            if i is not None:
                w = self._widget_at(i, pt)
                if w is not None:
                    self.fill_field(i, w)
                    return
                xref = annot_at(self.doc, i + 1, pt)
                self.selected = (i, xref) if xref else None
                if xref:
                    self.obj_sel = None
                    self._start_drag("move", pos)
                    self.viewport().update()
                    return
                if self.select_object_at(i, pt, added_only=True):      # something pdfdesk added: pick it up
                    self._start_drag("move", pos)
                    return
            self.obj_sel = None
            self._link_press = self._link_at(i, pt) if i is not None else None      # followed on release
            self._pan = (pos, self.horizontalScrollBar().value(), self.verticalScrollBar().value())
            self.viewport().setCursor(Qt.ClosedHandCursor)
            self.viewport().update()
            return
        if i is None:
            return
        if self.tool == "zoom":
            self.set_zoom(self.zoom / 1.25 if e.modifiers() & Qt.ShiftModifier else self.zoom * 1.25, anchor=pos)
            return
        if self.tool == "edit-text":
            self._commit_editor()           # clicking elsewhere keeps the edit, like Foxit
            ln = edit_cmds.line_at(self.doc, i + 1, pt)
            if ln:
                self._open_editor(i, ln)
            elif not self._page_words(i):
                self._hint(NO_TEXT_HINT)
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
                self.viewport().setCursor(self._hover_cursor(pos))
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

    def _hover_cursor(self, pos):
        """Hand: a form field shows it can be filled, a comment or added object that it can be picked up."""
        i, pt = self.view_to_page(pos)
        if i is not None:
            if self.tool == "hand":
                fields, comments, _links = self._hits(i)
                f = next((f for f in fields if f[0].contains(pt)), None)
                if f is not None:
                    return Qt.IBeamCursor if f[2] in FILLABLE else Qt.PointingHandCursor
                if any((r + (-3, -3, 3, 3)).contains(pt) for r, _x in comments):
                    return Qt.SizeAllCursor
                link = self._link_at(i, pt)
                key = (i, tuple(link["from"])) if link else None
                if key != self._hover_link:                       # say where a link goes, once per link
                    self._hover_link = key
                    if link:
                        self._hint(self._link_label(link))
                if link:
                    return Qt.PointingHandCursor
            if self._object_at(i, pt, added_only=self.tool == "hand") is not None:
                return Qt.SizeAllCursor
        return CURSORS.get(self.tool, Qt.CrossCursor)

    def _hits(self, i: int) -> tuple[list, list, list]:
        """What the mouse can point at on a page, read once per edit: hovering runs on every mouse move, and a
        tax form has hundreds of fields."""
        if i not in self._hit_cache:
            page = self.doc[i]
            fields = [(pymupdf.Rect(w.rect), w.xref, w.field_type) for w in page.widgets()]
            comments = [(pymupdf.Rect(a.rect), a.xref) for a in page.annots() or []
                        if a.type[0] not in (pymupdf.PDF_ANNOT_WIDGET, pymupdf.PDF_ANNOT_POPUP) and not a.flags & 2]
            self._hit_cache[i] = (fields, comments, page.get_links())
        return self._hit_cache[i]

    def _link_at(self, i: int, pt):
        return next((ln for ln in self._hits(i)[2] if pymupdf.Rect(ln["from"]).contains(pt)), None)

    def _link_target(self, link) -> tuple[int, float | None] | None:
        """(page index, y of the target in page coordinates or None) of a link inside the document."""
        if link["kind"] not in (pymupdf.LINK_GOTO, pymupdf.LINK_NAMED):
            return None
        page = link.get("page", -1)
        if page is None or not 0 <= page < self.doc.page_count:
            return None
        to = link.get("to")
        if to is None:
            return page, None
        pt = pymupdf.Point(to)
        if link["kind"] == pymupdf.LINK_NAMED:          # PyMuPDF gives a named destination in PDF space (y up)
            p = self.doc[page]
            pt = pt * p.transformation_matrix
        return page, pt.y

    def _link_label(self, link) -> str:
        target = self._link_target(link)
        if target:
            return tr("Link: go to page {n}", n=target[0] + 1)
        if link.get("uri"):
            return tr("Link: {uri}", uri=link["uri"])
        return tr("Link")

    def follow_link(self, link):
        """Go to a link's target in this document (Alt+Left comes back), or ask the window to open a web link."""
        target = self._link_target(link)
        if target:
            self._back.append((self.verticalScrollBar().value(), self.horizontalScrollBar().value()))
            page, y = target
            top = self.tops[page] + (y * self.zoom if y is not None and y > 0 else 0) - self.GAP
            self.verticalScrollBar().setValue(int(top))
            self._hint(tr("Page {n} — Alt+Left goes back", n=page + 1))
        elif link.get("uri"):
            self._emit(tool="open-url", url=link["uri"])

    def go_back(self):
        if self._back:
            v, h = self._back.pop()
            self.verticalScrollBar().setValue(v)
            self.horizontalScrollBar().setValue(h)

    def _widget_at(self, i: int, pt):
        f = next((f for f in self._hits(i)[0] if f[0].contains(pt)), None)
        return self._widget(i, f[1]) if f else None

    def _widget(self, i: int, xref: int):
        page = self.doc[i]
        w = next((w for w in page.widgets() if w.xref == xref), None)
        if w is not None:
            w.keep_page = page              # PyMuPDF unbinds a widget once its page object is collected
        return w

    def _page_words(self, i: int) -> list:
        if i not in self._words:
            self._words[i] = self.doc[i].get_text("words")
        return self._words[i]

    def _hint(self, text: str):
        self._emit(tool="hint", text=tr(text))

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        pos = e.position()
        if self._drag:
            self._finish_drag(pos)
            return
        if self._pan:
            start = self._pan[0]
            self._pan = None
            self.viewport().setCursor(self._hover_cursor(pos))
            link, self._link_press = self._link_press, None
            if link and abs(pos.x() - start.x()) + abs(pos.y() - start.y()) <= 4:     # a click, not a pan
                self.follow_link(link)
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
        elif t in TEXT_TOOLS and moved and not self._page_words(i):
            self._hint(NO_TEXT_HINT)
        elif t == "select":
            self.text_sel = (i, start, end) if moved and self._text_between(i, start, end) else None
        elif t == "textbox":                                     # a box (a click: one of default size), then type
            r = pymupdf.Rect(start, end).normalize() if moved else pymupdf.Rect(start, start + (180, 40))
            self.type_new_text(i, r.tl, t, rect=r, emit={"rect": r})
        elif t == "callout" and moved:                           # from the point to the box, then type
            r = pymupdf.Rect(end.x, end.y, end.x + 140, end.y + 50)
            self.type_new_text(i, end, t, rect=r, emit={"start": start, "stop": end})
        elif t in RECT_TOOLS:
            self._emit(tool=t, page=page, point=start, rect=pymupdf.Rect(start, end).normalize() if moved else None)
        elif t in LINE_TOOLS:
            if moved:
                self._emit(tool=t, page=page, start=start, stop=end)
        elif t in MARKUP_TOOLS:
            if moved:
                self._emit(tool=t, page=page, start=start, stop=end)
        elif t in TYPED_TOOLS:
            self.type_new_text(i, start, t)
        elif t in POINT_TOOLS:
            self._emit(tool=t, page=page, point=start)
        self.viewport().update()

    def mouseDoubleClickEvent(self, e):
        if self.tool in POLY_TOOLS and self._poly:
            self.finish_shape()
            return
        i, pt = self.view_to_page(e.position())
        if i is None:
            return
        if self.tool in TEXT_TOOLS:
            w = next((w for w in self._page_words(i) if pymupdf.Rect(w[:4]).contains(pt)), None)
            if w is not None:
                mid = (w[1] + w[3]) / 2
                a, b = pymupdf.Point(w[0] + 0.1, mid), pymupdf.Point(w[2] - 0.1, mid)
                if self.tool == "select":
                    self.text_sel = (i, a, b)
                    self.viewport().update()
                else:
                    self._emit(tool=self.tool, page=i + 1, start=a, stop=b)
            return
        if self.tool == "hand" and self.selected:
            i, xref = self.selected
            if not self.edit_comment_text(i, xref):
                self._emit(tool="edit-annot", page=i + 1, xref=xref)
            return
        if self.tool in ("edit-object", "hand") and self.obj_sel:
            o = next((o for o in self.page_objects(self.obj_sel[0]) if o.index == self.obj_sel[1]), None)
            if o is not None and (o.kind == "text" or o.size):
                ln = edit_cmds.line_at(self.doc, i + 1, pt)
                if ln:
                    self.obj_sel = None
                    self._open_editor(i, ln)

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
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace) and (self.obj_sel or self.selected):
            self.delete_selected()
            return
        if e.key() in ARROWS and (self.obj_sel or self.selected) and not e.modifiers() & Qt.ControlModifier:
            self.nudge(*ARROWS[e.key()], 10 if e.modifiers() & Qt.ShiftModifier else 1)
            return
        if e.matches(QKeySequence.StandardKey.SelectAll):
            self.select_page_text(self.current_page())
            return
        if self._navigate(e):
            return
        if e.matches(QKeySequence.StandardKey.Copy):
            if self.text_sel:
                QGuiApplication.clipboard().setText(self.selected_text())
            elif self.obj_sel or self.selected:
                self._emit(tool="copy")
            return
        if e.matches(QKeySequence.StandardKey.Cut) and (self.obj_sel or self.selected):
            self._emit(tool="cut")
            return
        if e.matches(QKeySequence.StandardKey.Paste):
            self.paste_here()
            return
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and (self._poly or self._ink):
            self.finish_shape()
            return
        if e.key() == Qt.Key_Escape:
            busy = self._poly or self._ink or self._press or self._drag or self.selected or self.text_sel or self.obj_sel
            self._poly = self._ink = self._press = self._drag = None
            self.selected = self.text_sel = self.obj_sel = None
            self.viewport().update()
            if not busy and self.tool != "hand":                # nothing to back out of: back to the Hand tool
                self._emit(tool="set-tool", name="hand")
            return
        super().keyPressEvent(e)

    def event(self, e):
        """Tab in a form: go to the first field on or after the current page (Shift+Tab: the last before it).
        Only a real key press: Qt also moves focus when a focused editor is hidden."""
        if e.type() == QEvent.Type.KeyPress and e.key() in (Qt.Key_Tab, Qt.Key_Backtab) and self._editor is None \
                and self.tool == "hand" and not self.readonly:
            fields = self._fields()
            if fields:
                here = self.current_page()
                if e.key() == Qt.Key_Tab:
                    i, xref = next((f for f in fields if f[0] >= here), fields[0])
                else:
                    i, xref = next((f for f in reversed(fields) if f[0] <= here), fields[-1])
                self._next_field({"page": i, "xref": xref}, 0)
                return True
        return super().event(e)

    def _navigate(self, e) -> bool:
        """Home / End and Ctrl+Home / Ctrl+End go to the first and last page; Space and Shift+Space page;
        Alt+Left returns from a followed link."""
        k, bar = e.key(), self.verticalScrollBar()
        if k == Qt.Key_Left and e.modifiers() & Qt.AltModifier:
            self.go_back()
        elif k == Qt.Key_Home:
            bar.setValue(0)
        elif k == Qt.Key_End:
            bar.setValue(bar.maximum())
        elif k == Qt.Key_Space:
            bar.setValue(bar.value() + (-1 if e.modifiers() & Qt.ShiftModifier else 1) * bar.pageStep())
        else:
            return False
        return True

    def nudge(self, dx: int, dy: int, step: float):
        """Move the selection by step points (arrow keys; Shift: 10 points)."""
        sel = self._selection()
        if not sel:
            return
        i, rect, _ = sel
        dx, dy = dx * step, dy * step
        if self.obj_sel:
            self._emit(tool="object-rect", page=i + 1, index=self.obj_sel[1], rect=rect + (dx, dy, dx, dy), nudge=True)
        else:
            self._emit(tool="move-annot", page=i + 1, xref=self.selected[1], dx=dx, dy=dy, nudge=True)

    def paste_here(self):
        """Paste at the mouse position when it is over a page, else onto the current page."""
        pos = QPointF(self.viewport().mapFromGlobal(QCursor.pos()))
        i, pt = self.view_to_page(pos)
        if i is None:
            i, pt = self.current_page(), None
        self._emit(tool="paste", page=i + 1, point=pt)

    def selected_text(self) -> str:
        if not self.text_sel:
            return ""
        return "\n".join(t for _r, t in self._text_between(*self.text_sel))

    def _text_between(self, i: int, a, b):
        if i not in self._words:
            self._words[i] = self.doc[i].get_text("words")
        return text_between(self.doc[i], a, b, self._words[i])

    # ---- right-click menus ----------------------------------------------------------------------------------
    def contextMenuEvent(self, e):
        """What the menu offers depends on what is under the mouse: selected text, a comment, an object (Edit
        Object), a form field, or the page itself."""
        pos = QPointF(e.pos())
        i, pt = self.view_to_page(pos)
        if self._editor is not None or self._poly or self._ink:
            return
        m = QMenu(self)
        if self.text_sel and self._on_text_sel(pos):
            self._text_menu(m)
        elif i is None:
            return
        elif xref := annot_at(self.doc, i + 1, pt):
            self.obj_sel, self.selected = None, (i, xref)
            self._annot_menu(m, i, xref)
        elif self.tool in ("hand", "edit-object") and self.select_object_at(i, pt, added_only=self.tool == "hand"):
            self._object_menu(m, i)
        elif w := self._widget_at(i, pt):
            self._field_menu(m, i, w)
        else:
            self._page_menu(m, i, pt)
        self.viewport().update()
        m.exec(e.globalPos())

    def _on_text_sel(self, pos) -> bool:
        i, a, b = self.text_sel
        return any(self.page_rect_to_view(i, r).adjusted(-4, -4, 4, 4).contains(pos)
                   for r, _t in self._text_between(i, a, b))

    def _sel_rects(self) -> list:
        i, a, b = self.text_sel
        return [r for r, _t in self._text_between(i, a, b)]

    def _text_menu(self, m: QMenu):
        i = self.text_sel[0]
        text = self.selected_text()
        rects = self._sel_rects()
        box = pymupdf.Rect(rects[0]) if rects else None
        for r in rects[1:]:
            box |= r
        m.addAction(tr("Copy"), lambda: QGuiApplication.clipboard().setText(text))
        m.addAction(tr("Select All"), lambda: self.select_page_text(i))
        m.addAction(tr("Deselect"), self.clear_text_selection)
        m.addSeparator()
        m.addAction(swatch(self.color_for("highlight")), tr("Highlight"), lambda: self._mark_selection("highlight"))
        fill_color_menu(m.addMenu(tr("Highlight in")), lambda c: self._mark_selection("highlight", c),
                        self.color_for("highlight"))
        for label, tool in (("Underline", "underline"), ("Strikeout", "strikeout"), ("Squiggly", "squiggly"),
                            ("Replace Text…", "replace-text"), ("Add Note to Text…", "highlight-note")):
            m.addAction(tr(label), lambda t=tool: self._mark_selection(t))
        m.addSeparator()
        short = " ".join(text.split())
        m.addAction(tr("Add Bookmark"), lambda: self._emit(tool="bookmark-here", page=i + 1, title=short[:120]))
        if box is not None:
            m.addAction(tr("Add Link…"), lambda: self._emit(tool="link", page=i + 1, rect=box))
            m.addAction(tr("Mark for Redaction"), lambda: self._emit(tool="redact-rects", page=i + 1, rects=rects))
        m.addSeparator()
        label = short if len(short) <= 28 else short[:26] + "…"
        m.addAction(tr("Find “{text}”", text=label), lambda: self._emit(tool="find", text=short))
        m.addAction(tr("Search the Web"), lambda: QDesktopServices.openUrl(
            QUrl("https://www.google.com/search?q=" + QUrl.toPercentEncoding(short[:300]).data().decode())))

    def clear_text_selection(self):
        self.text_sel = None
        self.viewport().update()

    def _annot_menu(self, m: QMenu, i: int, xref: int):
        st = comment_style(self.doc, i + 1, xref)
        restyle = lambda **kw: self._emit(tool="annot-style", page=i + 1, xref=xref, style=kw)
        m.addAction(tr("Properties…"), lambda: self._emit(tool="edit-annot", page=i + 1, xref=xref))
        m.addAction(tr("Reply…"), lambda: self._emit(tool="annot-reply", page=i + 1, xref=xref))
        sm = m.addMenu(tr("Set Status"))
        for s in ("Accepted", "Rejected", "Cancelled", "Completed", "None"):
            sm.addAction(tr(s), lambda s=s: self._emit(tool="annot-status", page=i + 1, xref=xref, state=s))
        m.addSeparator()
        for key, label in (("color", "Color"), ("text_color", "Text color")):
            if key in st["fields"]:
                fill_color_menu(m.addMenu(swatch(st[key]), tr(label)), lambda c, k=key: restyle(**{k: c}), st[key])
        if "fill" in st["fields"]:
            fill_color_menu(m.addMenu(swatch(st["fill"]), tr("Fill color")), lambda c: restyle(fill=c), st["fill"], tr("No fill"))
        if "fontsize" in st["fields"]:
            sz = m.addMenu(tr("Font size"))
            for n in (8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 36, 48):
                a = sz.addAction(str(n), lambda n=n: restyle(fontsize=n))
                a.setCheckable(True)
                a.setChecked(abs(st["fontsize"] - n) < 0.05)
        if "width" in st["fields"]:
            wm = m.addMenu(tr("Line width"))
            for n in (0.5, 1, 1.5, 2, 3, 4, 6):
                a = wm.addAction(f"{n:g} pt", lambda n=n: restyle(width=n))
                a.setCheckable(True)
                a.setChecked(abs(st["width"] - n) < 0.05)
        om = m.addMenu(tr("Opacity"))
        for n in (100, 75, 50, 25):
            a = om.addAction(f"{n} %", lambda n=n: restyle(opacity=n / 100))
            a.setCheckable(True)
            a.setChecked(round(st["opacity"] * 100) == n)
        tool = ANNOT_TOOLS.get(st["type"])
        col = st.get("text_color") if st["type"] == "FreeText" else st.get("color")
        if tool and col:
            m.addAction(tr("Use as Default Color"), lambda: self._emit(tool="tool-color", name=tool, color=tuple(col)))
        if st["content"]:
            m.addAction(tr("Copy text"), lambda: QGuiApplication.clipboard().setText(st["content"]))
        m.addSeparator()
        m.addAction(tr("Copy"), lambda: self._emit(tool="copy"))
        m.addAction(tr("Cut"), lambda: self._emit(tool="cut"))
        m.addAction(tr("Delete"), lambda: self.delete_selected())

    def _object_menu(self, m: QMenu, i: int):
        n = self.obj_sel[1]
        o = next(o for o in self.page_objects(i) if o.index == n)
        page = i + 1
        m.addAction(tr("Copy"), lambda: self._emit(tool="copy"))
        m.addAction(tr("Cut"), lambda: self._emit(tool="cut"))
        m.addSeparator()
        if o.kind == "text":
            text = self.doc[i].get_text(clip=o.rect + (-1, -1, 1, 1)).strip()
            m.addAction(tr("Copy text"), lambda: QGuiApplication.clipboard().setText(text))
            m.addAction(tr("Edit text"), lambda: self._emit(tool="set-tool", name="edit-text"))
        if o.size:
            sz = m.addMenu(tr("Font size ({size} pt)", size=f"{o.size:.3g}"))
            for pt in (6, 7, 8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 36, 48):
                a = sz.addAction(str(pt), lambda pt=pt: self._emit(tool="object-fontsize", page=page, index=n, size=pt))
                a.setCheckable(True)
                a.setChecked(abs(o.size - pt) < 0.05)
        m.addAction(tr("Copy as Image"), lambda: self._copy_object_image(page, n))
        m.addAction(tr("Export as Image…"), lambda: self._emit(tool="object-export", page=page, index=n))
        m.addSeparator()
        for label, kw in (("Rotate Right 90°", {"angle": 90}), ("Rotate Left 90°", {"angle": -90}),
                          ("Flip Horizontal", {"flip": "h"}), ("Flip Vertical", {"flip": "v"})):
            m.addAction(tr(label), lambda kw=kw: self._emit(tool="object-turn", page=page, index=n, **kw))
        m.addAction(tr("Position && Size…"), lambda: self._emit(tool="object-geometry", page=page, index=n,
                                                             rect=pymupdf.Rect(o.rect)))
        m.addSeparator()
        m.addAction(tr("Add Link…"), lambda: self._emit(tool="link", page=page, rect=pymupdf.Rect(o.rect)))
        m.addAction(tr("Mark for Redaction"), lambda: self._emit(tool="redact-rects", page=page, rects=[pymupdf.Rect(o.rect)]))
        m.addSeparator()
        m.addAction(tr("Delete"), lambda: self.delete_selected())

    def _copy_object_image(self, page: int, index: int):
        data, _ext = objects.export_image(self.doc, page, index, dpi=200)
        QGuiApplication.clipboard().setImage(QImage.fromData(data))

    def _field_menu(self, m: QMenu, i: int, w):
        xref, name = w.xref, w.field_name
        value = w.field_value if isinstance(w.field_value, str) else ""
        m.addAction(tr("Fill in…"), lambda: self.fill_field(i, self._widget(i, xref)))
        if value:
            m.addAction(tr("Copy Value"), lambda: QGuiApplication.clipboard().setText(value))
        m.addAction(tr("Clear Value"), lambda: self._emit(tool="field-reset", names=[name]))
        m.addSeparator()
        m.addAction(tr("Reset All Fields"), lambda: self._emit(tool="field-reset", names=None))
        m.addAction(tr("Delete Field “{name}”", name=name), lambda: self._emit(tool="field-delete", name=name))

    def _page_menu(self, m: QMenu, i: int, pt):
        page = i + 1
        if self.text_sel:
            m.addAction(tr("Copy"), lambda: QGuiApplication.clipboard().setText(self.selected_text()))
        what = clipboard.describe()
        if what:
            m.addAction(tr(f"Paste {what} Here"), lambda: self._emit(tool="paste", page=page, point=pt))
        m.addAction(tr("Select all text on this page"), lambda: self.select_page_text(i))
        m.addAction(tr("Copy Page as Image"), lambda: QGuiApplication.clipboard().setImage(
            QImage.fromData(self.doc[i].get_pixmap(dpi=150, alpha=False).tobytes("png"))))
        m.addSeparator()
        for label, tool in (("Hand", "hand"), ("Select Text", "select"), ("Edit Object", "edit-object")):
            a = m.addAction(tr(label), lambda t=tool: self._emit(tool="set-tool", name=t))
            a.setCheckable(True)
            a.setChecked(self.tool == tool)
        m.addSeparator()
        m.addAction(tr("Add note here…"), lambda: self._emit(tool="note", page=page, point=pt))
        m.addAction(tr("Add typewriter text here…"), lambda: self.type_new_text(i, pt, "typewriter"))
        m.addAction(tr("Add text here…"), lambda: self.type_new_text(i, pt, "add-text"))
        m.addAction(tr("Add image here…"), lambda: self._emit(tool="image-here", page=page, point=pt))
        m.addAction(tr("Add Bookmark for This Page"), lambda: self._emit(tool="bookmark-here", page=page, title=tr("Page {n}", n=page)))
        m.addSeparator()
        if i > 0:
            m.addAction(tr("Previous Page"), lambda: self.goto(i - 1))
        if i + 1 < self.doc.page_count:
            m.addAction(tr("Next Page"), lambda: self.goto(i + 1))
        m.addAction(tr("Find…"), lambda: self._emit(tool="app", name="find"))
        zm = m.addMenu(tr("Zoom"))
        zm.addAction(tr("Zoom in"), lambda: self.set_zoom(self.zoom * 1.25))
        zm.addAction(tr("Zoom out"), lambda: self.set_zoom(self.zoom / 1.25))
        zm.addAction(tr("Actual size"), lambda: self.set_zoom(1.0))
        zm.addAction(tr("Fit width"), self.fit_width)
        zm.addAction(tr("Fit page"), self.fit_page)
        m.addSeparator()
        pg = m.addMenu(tr("Page {n}", n=page))
        for label, name in (("Rotate right", "rotate-right"), ("Rotate left", "rotate-left"),
                            ("Insert blank page after", "insert-blank"), ("Insert from file after…", "insert-file"),
                            ("Duplicate", "duplicate"), ("Extract…", "extract"), ("Delete", "delete")):
            pg.addAction(tr(label), lambda n=name: self._emit(tool="page-command", name=n, pages=[i]))
        m.addSeparator()
        m.addAction(tr("Print…"), lambda: self._emit(tool="app", name="print"))
        m.addAction(tr("Document Properties…"), lambda: self._emit(tool="app", name="properties"))

    def delete_selected(self):
        if self.obj_sel:
            (i, n), self.obj_sel = self.obj_sel, None
            self._emit(tool="delete-object", page=i + 1, index=n)
        elif self.selected:
            (i, xref), self.selected = self.selected, None
            self._emit(tool="delete-annot", page=i + 1, xref=xref)

    def select_page_text(self, i: int):
        w = self._page_words(i)
        if not w:
            self._hint(NO_TEXT_HINT)
        if w:
            self.text_sel = (i, pymupdf.Point(w[0][:2]), pymupdf.Point(w[-1][2:4]))
            self.viewport().update()

    def _mark_selection(self, tool: str, color=None):
        i, a, b = self.text_sel
        self.text_sel = None
        self._emit(tool=tool, page=i + 1, start=a, stop=b, **({"color": color} if color else {}))

    def color_for(self, tool: str):
        """The color new comments of this tool get: the user's choice, else the tool's default."""
        return self.tool_colors.get(tool) or DEFAULT_COLORS.get(tool)

    def _preview(self, tool: str) -> QColor:
        if tool == "select" or not self.color_for(tool):
            return SEL_COLORS[tool]
        c = qcolor(self.color_for(tool))
        c.setAlpha(110 if tool == "highlight" else 70)
        return c

    # ---- editors on the page: Edit Text, new text, a comment's text, form fields --------------------------
    def _start_editor(self, ed, target: dict):
        """target: what the editor changes, {"kind": "line" | "new" | "annot" | "field", "page", "rect", …}."""
        self._commit_editor()
        self._editor, self._edit_target = ed, target
        if isinstance(ed, InlineFieldEditor):
            ed.committed.connect(self._commit_editor)
        else:
            ed.committed.connect(lambda: self._commit_editor())
        ed.cancelled.connect(self._close_editor)
        self._place_editor()
        ed.show()
        ed.focus()
        self.viewport().update()

    def _open_editor(self, i: int, ln):
        """Edit one line of page text where it is."""
        ed = InlineTextEditor(self.viewport(), ln.text, ln.size, ln.color, self.zoom)
        self._start_editor(ed, {"kind": "line", "page": i, "rect": ln.rect, "line": ln})

    def type_new_text(self, i: int, point, tool: str, rect=None, emit: dict | None = None):
        """Typewriter, Add Text, Note, Text box, Callout: type where the comment goes; Enter starts a new line,
        clicking elsewhere, Escape or Ctrl+Enter keeps the text. emit: what the tool action carries besides the
        text (default: the point). Only Typewriter and Add Text offer a size and a color."""
        styled = tool in ("typewriter", "add-text")
        size = prefs.get_float(f"text_size/{tool}", 10.0) if styled else 11.0
        color = (self.color_for(tool) or (0, 0, 0)) if styled else (0, 0, 0)
        ed = InlineTextEditor(self.viewport(), "", size, color, self.zoom, multiline=True, escape_keeps=True,
                              controls=styled)
        pt = pymupdf.Point(point)
        box = pymupdf.Rect(rect) if rect is not None else pymupdf.Rect(pt.x, pt.y, pt.x + 4, pt.y + size * 1.3 + 4)
        self._start_editor(ed, {"kind": "new", "page": i, "rect": box, "tool": tool, "styled": styled,
                                "emit": emit if emit is not None else {"point": pt}})

    def edit_comment_text(self, i: int, xref: int) -> bool:
        """A typewriter or text box comment: change its text where it is. False for other comments."""
        st = comment_style(self.doc, i + 1, xref)
        if st["type"] != "FreeText":
            return False
        page = self.doc[i]
        a = next((a for a in page.annots() or [] if a.xref == xref), None)
        if a is None:
            return False
        ed = InlineTextEditor(self.viewport(), st["content"], st.get("fontsize") or 11, st.get("text_color"),
                              self.zoom, multiline=True, escape_keeps=False)
        self._start_editor(ed, {"kind": "annot", "page": i, "rect": pymupdf.Rect(a.rect), "xref": xref,
                                "text": st["content"], "size": st.get("fontsize"), "color": st.get("text_color")})
        return True

    def fill_field(self, i: int, w):
        """Type or pick a field's value on the page; a check box or radio button just toggles."""
        if self.readonly or w.field_type not in FILLABLE or w.field_flags & 1:      # bit 1: read-only field
            self._emit(tool="fill-field", page=i + 1, xref=w.xref)
            return
        kind = FILLABLE[w.field_type]
        opts = [o[1] if isinstance(o, (list, tuple)) else o for o in (w.choice_values or [])]
        value = w.field_value if isinstance(w.field_value, str) else ""
        rect = pymupdf.Rect(w.rect)
        px = int((w.text_fontsize or min(12.0, rect.height * 0.7)) * self.zoom)
        ed = InlineFieldEditor(self.viewport(), kind, value, opts, px, multiline=bool(w.field_flags & (1 << 12)),
                               editable=bool(w.field_flags & (1 << 18)))
        self._start_editor(ed, {"kind": "field", "page": i, "rect": rect, "xref": w.xref, "value": value})

    def _fields(self) -> list[tuple[int, int]]:
        """(page index, xref) of every field that can be typed into, in document order."""
        out = []
        for i in range(self.doc.page_count):
            page = self.doc[i]
            out += [(i, w.xref) for w in page.widgets() if w.field_type in FILLABLE and not w.field_flags & 1]
        return out

    def _next_field(self, target: dict, step: int):
        fields = self._fields()
        here = (target["page"], target["xref"])
        if here not in fields:
            return
        i, xref = fields[(fields.index(here) + step) % len(fields)]
        w = self._widget(i, xref)
        if w is None:
            return
        self.reveal(i, w.rect)
        self.fill_field(i, w)

    def _commit_editor(self, step: int = 0):
        """Keep what the open editor holds, as one undoable step; step moves on to the next form field."""
        if self._editor is None:
            return
        ed, t = self._editor, self._edit_target
        self._close_editor()
        page = t["page"] + 1
        if t["kind"] == "field":
            value = ed.value()
            if value != t["value"]:
                self._emit(tool="field-value", page=page, xref=t["xref"], value=value)
            if step:
                self._next_field(t, step)
            return
        text, size, color = ed.text(), ed.size(), ed.color()
        if t["kind"] == "new":
            if text.strip():
                style = {"size": size, "color": color} if t["styled"] else {}
                self._emit(tool=t["tool"], page=page, text=text.rstrip("\n"), **t["emit"], **style)
            return
        if t["kind"] == "annot":
            style = {}
            if text != t["text"]:
                style["text"] = text
            if t["size"] and abs(size - t["size"]) > 0.05:
                style["fontsize"] = size
            if color and t["color"] and any(abs(a - b) > 1 / 255 for a, b in zip(color, t["color"])):
                style["text_color"] = color
            if style:
                self._emit(tool="annot-style", page=page, xref=t["xref"], style=style)
            return
        ln = t["line"]
        changed = {}
        if abs(size - ln.size) > 0.05:
            changed["size"] = size
        if color and any(abs(a - b) > 1 / 255 for a, b in zip(color, ln.color)):
            changed["color"] = color
        if text != ln.text or changed:
            center = ln.rect.tl + (ln.rect.br - ln.rect.tl) / 2
            self._emit(tool="edit-text-commit", page=page, point=center, text=text, **changed)

    def _close_editor(self):
        if self._editor is not None:
            ed, self._editor = self._editor, None
            self._edit_target = None
            self._hover_line = None
            self.setFocus()                     # before hiding it, so Qt does not pass the focus elsewhere
            ed.hide()
            ed.deleteLater()
            self.viewport().update()

    # ---- search ----------------------------------------------------------------------------------------------
    def find(self, text: str) -> int:
        """Mark every hit and show the first one at or after the current page."""
        self.highlights.clear()
        self.hits, self.hit, self.find_text = [], -1, text
        for i, p in enumerate(self.doc):
            rs = search.find(p, text) if text else []
            if rs:
                self.highlights[i] = rs
                self.hits += [(i, r) for r in rs]
        if self.hits:
            here = self.current_page()
            self.show_hit(next((k for k, (i, _r) in enumerate(self.hits) if i >= here), 0))
        self.viewport().update()
        return len(self.hits)

    def show_hit(self, k: int):
        """Make hit k the current one and scroll it into view, a third down from the top."""
        if not self.hits:
            return
        self.hit = k % len(self.hits)
        self.reveal(*self.hits[self.hit])

    def reveal(self, i: int, rect):
        """Scroll so a rectangle on page i is in view, a third down from the top, unless it already is."""
        v = self.page_rect_to_view(i, rect)
        vp = self.viewport()
        if v.top() < 0 or v.bottom() > vp.height():
            bar = self.verticalScrollBar()
            bar.setValue(int(bar.value() + v.top() - vp.height() / 3))
        if v.left() < 0 or v.right() > vp.width():
            bar = self.horizontalScrollBar()
            bar.setValue(int(bar.value() + v.left() - vp.width() / 3))
        self.viewport().update()

