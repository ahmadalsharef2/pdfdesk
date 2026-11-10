"""Not a pytest test: run it by hand. User journeys through the real window with real mouse and key events, on
many kinds of documents. Each step saves a screenshot and prints what a user would notice: the status message,
the tool, the selection, the undo label, and whether the result landed where the mouse was.

    QT_QPA_PLATFORM=offscreen .venv/bin/python -u tests/journeys.py OUTDIR [journey …]

Lines starting with "!!" are problems: something a user would find wrong or rough.
"""
from __future__ import annotations

import faulthandler
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tests")]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_home = tempfile.mkdtemp(prefix="pdfdesk-journeys-")
os.environ["XDG_CONFIG_HOME"] = os.path.join(_home, "config")
os.environ["XDG_DATA_HOME"] = os.path.join(_home, "data")

import pymupdf  # noqa: E402
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QContextMenuEvent, QKeyEvent, QMouseEvent, QWheelEvent  # noqa: E402
from PySide6.QtWidgets import (QApplication, QColorDialog, QDialog, QFileDialog, QInputDialog, QMenu,  # noqa: E402
                               QMessageBox)

from conftest import make_contract  # noqa: E402
from pdfdesk.commands import run as run_cmd  # noqa: E402
from pdfdesk.gui import dialogs  # noqa: E402
from pdfdesk.gui.app import Main  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp(prefix="journeys-")
os.makedirs(OUT, exist_ok=True)
CORPUS = os.path.join(ROOT, "tests", "corpus")
app = QApplication([])
TMP = tempfile.mkdtemp(prefix="pdfdesk-journey-docs-")


# ---- documents -----------------------------------------------------------------------------------------------
def doc_contract() -> str:
    p = os.path.join(TMP, "contract.pdf")
    make_contract(p)
    return p


def doc_scanned() -> str:
    """A page with no text layer, as a scanner makes it."""
    src = pymupdf.open(doc_contract())
    out = pymupdf.open()
    for page in src:
        pix = page.get_pixmap(dpi=120)
        p = out.new_page(width=page.rect.width, height=page.rect.height)
        p.insert_image(p.rect, pixmap=pix)
    path = os.path.join(TMP, "scanned.pdf")
    out.save(path)
    return path


def doc_odd_pages() -> str:
    """A4 portrait, A4 landscape, a page rotated 90 degrees and an A3 page."""
    d = pymupdf.open()
    for n, (w, h, rot) in enumerate([(595, 842, 0), (842, 595, 0), (595, 842, 90), (842, 1191, 0)], 1):
        p = d.new_page(width=w, height=h)
        p.insert_text((72, 90), f"Odd page {n}: {w}x{h} rotation {rot}", fontsize=16)
        p.insert_text((72, 130), "Some body text to select and highlight on this page.", fontsize=11)
        p.draw_rect(pymupdf.Rect(72, 160, 272, 260), color=(0, 0, 1), fill=(0.8, 0.9, 1))
        p.set_rotation(rot)
    path = os.path.join(TMP, "odd.pdf")
    d.save(path)
    return path


def doc_images() -> str:
    """Text, an image and a vector shape on one page, for Edit Object."""
    d = pymupdf.open()
    p = d.new_page()
    p.insert_text((72, 80), "A page with an image and a shape", fontsize=18)
    src = pymupdf.open(doc_contract())
    png = src[0].get_pixmap(dpi=40).tobytes("png")
    p.insert_image(pymupdf.Rect(72, 120, 272, 380), stream=png)
    p.draw_rect(pymupdf.Rect(320, 120, 520, 220), color=(1, 0, 0), fill=(1, 0.9, 0.9), width=2)
    p.insert_text((320, 260), "Caption text next to the shape", fontsize=12)
    path = os.path.join(TMP, "images.pdf")
    d.save(path)
    return path


def web(name: str) -> str | None:
    p = os.path.join(CORPUS, "web", name)
    return p if os.path.exists(p) else None


def manual() -> str | None:
    p = os.path.join(CORPUS, "foxit", "manual.pdf")
    return p if os.path.exists(p) else None


# ---- dialogs answer themselves; record what was asked ---------------------------------------------------------
asked: list[str] = []
answers = {"text": "Journey text", "item": 0}


def _exec_once(self):
    asked.append(f"dialog {type(self).__name__}: {self.windowTitle()}")
    if getattr(self, "_answered", False):
        return QDialog.Rejected
    self._answered = True
    if isinstance(self, dialogs.TextDialog):
        self.edit.setPlainText(answers["text"])
    return QDialog.Accepted


QDialog.exec = _exec_once
for _cls in (QMessageBox, QInputDialog, QFileDialog, QColorDialog):
    _cls.exec = _exec_once
QInputDialog.getText = staticmethod(lambda p, t, lab, *a, **k: (asked.append(f"input: {t}: {lab}"), (answers["text"], True))[1])
QInputDialog.getMultiLineText = staticmethod(lambda p, t, lab, *a, **k: (asked.append(f"input: {t}"), (answers["text"], True))[1])
QInputDialog.getInt = staticmethod(lambda p, t, lab, v=1, *a, **k: (asked.append(f"input: {t}"), (v, True))[1])
QInputDialog.getItem = staticmethod(lambda p, t, lab, items, *a, **k: (asked.append(f"input: {t}"), (items[0], True))[1])
QColorDialog.getColor = staticmethod(lambda *a, **k: QColor(200, 30, 30))
QMessageBox.question = staticmethod(lambda p, t, text, *a, **k: (asked.append(f"question: {t}: {text}"), QMessageBox.Yes)[1])
for _n in ("information", "warning", "critical"):
    setattr(QMessageBox, _n, staticmethod(lambda p, t, text, *a, _k=_n, **k: (asked.append(f"{_k}: {t}: {text}"), QMessageBox.Ok)[1]))
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (os.path.join(TMP, f"saved-{time.time_ns()}.pdf"), ""))
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (doc_contract(), ""))
menus: list[list[str]] = []


def _menu_exec(self, *a, **k):
    def walk(m, prefix=""):
        out = []
        for act in m.actions():
            if act.isSeparator():
                continue
            out.append(prefix + act.text().replace("&&", "&"))
            if act.menu():
                out += walk(act.menu(), prefix + "  ")
        return out
    menus.append(walk(self))
    return None


class _RecordingMenu(QMenu):
    """Qt's own QMenu.exec ignores a patched class attribute; a Python subclass is always used."""
    def exec(self, *a, **k):
        return _menu_exec(self, *a, **k)


from pdfdesk.gui import app as _app_mod, panels as _panels_mod, viewer as _viewer_mod  # noqa: E402
for _m in (_app_mod, _panels_mod, _viewer_mod):
    _m.QMenu = _RecordingMenu


# ---- the session ---------------------------------------------------------------------------------------------
class Session:
    def __init__(self, name: str, width=1360, height=860):
        self.name = name
        self.w = Main()
        self.w.resize(width, height)
        self.w.show()
        app.processEvents()
        self.step = 0
        self.problems = 0

    @property
    def v(self):
        return self.w.cur()

    def open(self, path: str):
        t0 = time.time()
        v = self.w.open_path(path)
        app.processEvents()
        dt = time.time() - t0
        self.note(f"opened {os.path.basename(path)} in {dt:.2f} s, zoom {v.zoom:.2f} fit {v.fit_mode}")
        if dt > 3:
            self.bad(f"opening took {dt:.1f} s")
        return v

    def note(self, text: str):
        print(f"   {self.name}: {text}", flush=True)

    def bad(self, text: str):
        self.problems += 1
        print(f"!! {self.name}: {text}", flush=True)

    def shot(self, label: str):
        app.processEvents()
        self.step += 1
        path = os.path.join(OUT, f"{self.name}-{self.step:02d}-{label}.png")
        self.w.grab().save(path)
        return path

    def state(self) -> dict:
        v = self.v
        return {"msg": self.w.msg_label.toolTip() or self.w.msg_label.text(), "tool": self.w.tool,
                "selected": v.selected if v else None, "obj": v.obj_sel if v else None,
                "undo": v.undo_stack[-1][0] if v and v.undo_stack else None,
                "title": self.w.windowTitle(), "page": v.current_page() if v else None}

    # mouse and keys, sent to the viewport like real input
    def vpos(self, page: int, x: float, y: float) -> QPointF:
        """View position of a point in unrotated page coordinates of a 0-based page."""
        return self.v.page_point_to_view(page, pymupdf.Point(x, y))

    def _send(self, kind, pos: QPointF, button=Qt.LeftButton, mods=Qt.NoModifier):
        faulthandler.dump_traceback_later(45, exit=True)       # a step that blocks prints where, then ends the run
        t = {"press": QEvent.MouseButtonPress, "move": QEvent.MouseMove, "release": QEvent.MouseButtonRelease,
             "double": QEvent.MouseButtonDblClick}[kind]
        buttons = Qt.NoButton if kind == "release" else button
        vp = self.v.viewport()
        ev = QMouseEvent(t, pos, vp.mapToGlobal(pos), button if kind != "move" else Qt.NoButton, buttons, mods)
        QApplication.sendEvent(vp, ev)
        app.processEvents()

    def click(self, pos, mods=Qt.NoModifier):
        self._send("press", pos, mods=mods)
        self._send("release", pos, mods=mods)

    def double(self, pos):
        self._send("press", pos)
        self._send("release", pos)
        self._send("double", pos)
        self._send("release", pos)

    def drag(self, a: QPointF, b: QPointF, steps=6):
        self._send("press", a)
        for k in range(1, steps + 1):
            self._send("move", QPointF(a.x() + (b.x() - a.x()) * k / steps, a.y() + (b.y() - a.y()) * k / steps))
        self._send("release", b)

    def hover(self, pos):
        vp = self.v.viewport()
        QApplication.sendEvent(vp, QMouseEvent(QEvent.MouseMove, pos, vp.mapToGlobal(pos), Qt.NoButton, Qt.NoButton,
                                               Qt.NoModifier))
        app.processEvents()
        return vp.cursor().shape()

    def key(self, k, mods=Qt.NoModifier, text=""):
        faulthandler.dump_traceback_later(45, exit=True)
        target = QApplication.focusWidget() or self.v
        ed = self.v._editor if self.v is not None else None
        if ed is not None and not ed.isAncestorOf(target):       # an inactive test window has no focus widget
            target = ed.edit
        QApplication.sendEvent(target, QKeyEvent(QEvent.KeyPress, k, mods, text))
        QApplication.sendEvent(target, QKeyEvent(QEvent.KeyRelease, k, mods, text))
        app.processEvents()

    def type_text(self, text: str):
        for ch in text:
            self.key(0, Qt.NoModifier, ch)

    def wheel(self, pos, dy=120, mods=Qt.NoModifier):
        vp = self.v.viewport()
        ev = QWheelEvent(pos, vp.mapToGlobal(pos), QPoint(), QPoint(0, dy), Qt.NoButton, mods, Qt.NoScrollPhase, False)
        QApplication.sendEvent(vp, ev)
        app.processEvents()

    def context(self, pos) -> list[str]:
        menus.clear()
        vp = self.v.viewport()
        QApplication.sendEvent(vp, QContextMenuEvent(QContextMenuEvent.Mouse, pos.toPoint(), vp.mapToGlobal(pos.toPoint())))
        app.processEvents()
        return menus[-1] if menus else []

    def tool(self, name: str):
        self.w.set_tool(name)
        app.processEvents()

    def annots(self, page: int) -> list:
        p = self.v.doc[page]
        return [(a.type[1], pymupdf.Rect(a.rect), a.xref) for a in p.annots()]

    def close(self):
        for v in self.w.views():
            v.modified = False
        self.w.close()
        app.processEvents()


JOURNEYS: dict[str, callable] = {}


def journey(fn):
    JOURNEYS[fn.__name__] = fn
    return fn


# ---- journeys --------------------------------------------------------------------------------------------------
def _check_new_comment(s: Session, page: int, before: int, what: str, near: pymupdf.Rect | None):
    after = s.annots(page)
    st = s.state()
    if len(after) <= before:
        s.bad(f"{what}: no comment was made ({st['msg']!r}; asked {asked[-3:]})")
        return None
    kind, rect, xref = after[-1]
    if near is not None and not (rect + (-12, -12, 12, 12)).intersects(near):
        s.bad(f"{what}: made at {rect} but the mouse was at {near}")
    if not st["undo"]:
        s.bad(f"{what}: nothing to undo afterwards")
    if s.v.selected is None or s.v.selected[1] != xref:
        s.bad(f"{what}: the new {kind} is not selected afterwards")
    if st["tool"] != s.w.tool:
        s.bad(f"{what}: tool changed to {st['tool']}")
    return kind, rect, xref


@journey
def comment_tools(path=None, zoom=1.0, tag="contract", pg=0):
    """Every comment tool with real mouse input, at a given zoom, on a given page."""
    s = Session(f"comments-{tag}-{int(zoom * 100)}")
    s.open(path or doc_contract())
    s.v.set_zoom(zoom)
    s.v.goto(pg)
    app.processEvents()
    # text markup over the "Client: Acme Ltd" line of the contract (y ~ 106)
    words = s.v.doc[pg].get_text("words")
    line = [w for w in words if abs(w[1] - words[min(2, len(words) - 1)][1]) < 2] or words[:3]
    x0, y0, x1, y1 = line[0][0], line[0][1], line[-1][2], line[-1][3]
    ymid = (y0 + y1) / 2
    for t in ("highlight", "underline", "strikeout", "squiggly"):
        s.tool(t)
        n = len(s.annots(pg))
        s.drag(s.vpos(pg, x0 + 1, ymid), s.vpos(pg, x1 - 1, ymid))
        _check_new_comment(s, pg, n, t, pymupdf.Rect(x0, y0, x1, y1))
    s.shot("markup")
    shapes = [("rectangle", (100, 300, 200, 360)), ("oval", (220, 300, 320, 360)), ("area-highlight", (340, 300, 440, 360)),
              ("textbox", (100, 380, 260, 430)), ("stamp", (300, 380, 460, 440)), ("line", (100, 460, 250, 500)),
              ("arrow", (270, 460, 420, 500)), ("callout", (100, 520, 200, 560))]
    for t, r in shapes:
        s.tool(t)
        n = len(s.annots(pg))
        s.drag(s.vpos(pg, r[0], r[1]), s.vpos(pg, r[2], r[3]))
        if t in ("textbox", "callout"):
            if s.v._editor is None:
                s.bad(f"{t}: no editor to type the text on the page")
            else:
                s.type_text(f"{t} text")
                s.key(Qt.Key_Escape)
        res = _check_new_comment(s, pg, n, t, pymupdf.Rect(r))
        if res and t in ("rectangle", "oval") and abs(res[1].width - (r[2] - r[0])) > 4:
            s.bad(f"{t}: width {res[1].width:.0f} instead of {r[2] - r[0]}")
    s.shot("shapes")
    for t, (x, y) in (("note", (480, 300)), ("typewriter", (100, 600)), ("file", (520, 300)), ("add-text", (100, 650))):
        s.tool(t)
        n = len(s.annots(pg))
        objs = len(s.v.page_objects(pg))
        asked.clear()
        s.click(s.vpos(pg, x, y))
        if t in ("typewriter", "add-text", "note"):
            if s.v._editor is None:
                s.bad(f"{t}: clicking opened no editor on the page")
                continue
            ed = s.v._editor
            r = s.v.page_rect_to_view(pg, s.v._edit_target["rect"])
            if abs(ed.geometry().x() - r.x()) > 6 or abs(ed.geometry().y() - r.y()) > 6:
                s.bad(f"{t}: the editor is at {ed.geometry().topLeft()} but the click was at {r.topLeft()}")
            s.type_text("First line")
            s.key(Qt.Key_Return)
            s.type_text("Second")
            s.shot(f"typing-{t}")
            s.key(Qt.Key_Escape)
        if t == "add-text":
            if len(s.v.page_objects(pg)) <= objs:
                s.bad(f"{t}: no text was added ({asked})")
            elif "Second" not in s.v.doc[pg].get_text():
                s.bad(f"{t}: the second typed line is missing")
            if not s.v.obj_sel:
                s.bad(f"{t}: the added text is not selected")
        else:
            res = _check_new_comment(s, pg, n, t, pymupdf.Rect(x - 30, y - 30, x + 30, y + 30))
            if t == "typewriter" and res:
                a = next(a for a in s.v.doc[pg].annots() if a.xref == res[2])
                if a.info["content"] != "First line\nSecond":
                    s.bad(f"typewriter: content {a.info['content']!r}")
            if asked:
                s.note(f"{t}: asked {asked}")
    for t, pts in (("polygon", [(100, 700), (180, 700), (140, 760)]), ("cloud", [(220, 700), (300, 700), (260, 760)]),
                   ("polyline", [(340, 700), (420, 720), (380, 760)])):
        s.tool(t)
        n = len(s.annots(pg))
        for x, y in pts:
            s.click(s.vpos(pg, x, y))
        s.double(s.vpos(pg, *pts[-1]))
        _check_new_comment(s, pg, n, t, pymupdf.Rect(min(p[0] for p in pts), min(p[1] for p in pts),
                                                     max(p[0] for p in pts), max(p[1] for p in pts)))
    s.tool("pencil")
    n = len(s.annots(pg))
    s.drag(s.vpos(pg, 450, 700), s.vpos(pg, 520, 760))
    s.key(Qt.Key_Return)
    _check_new_comment(s, pg, n, "pencil", pymupdf.Rect(450, 700, 520, 760))
    s.shot("all-comments")
    s.key(Qt.Key_Escape)
    s.key(Qt.Key_Escape)
    if s.w.tool != "hand":
        s.bad(f"Escape with nothing selected leaves the {s.w.tool} tool on")
    count = s.w.comments.topLevelItemCount() if hasattr(s.w.comments, "topLevelItemCount") else None
    s.note(f"comments panel rows: {count}, annotations on the page: {len(s.annots(pg))}")
    # undo everything one by one: every step labelled
    labels = [lab for lab, _ in reversed(s.v.undo_stack)]
    s.note(f"undo labels: {labels}")
    s.close()


@journey
def comment_zooms():
    comment_tools(zoom=0.5, tag="contract")
    comment_tools(zoom=3.0, tag="contract")
    comment_tools(doc_odd_pages(), 1.0, "rotated", pg=2)
    if manual():
        comment_tools(manual(), 1.0, "manual", pg=20)


@journey
def hand_on_comments(path=None, tag="contract"):
    """Select, move, resize, edit, recolor, copy/paste, delete comments with the Hand tool and the keyboard."""
    s = Session(f"hand-{tag}")
    s.open(path or doc_contract())
    s.v.set_zoom(1.0)
    s.v.goto(0)
    app.processEvents()
    s.w.apply("setup", lambda d: (run_cmd("Comment.Rectangle", d, 1, (100, 300, 200, 360)),
                                  run_cmd("Comment.Typewriter", d, 1, (100, 420), "Typed note"),
                                  run_cmd("Comment.Line", d, 1, (250, 300), (400, 360))))
    s.tool("hand")
    rect_xref = next(x for k, r, x in s.annots(0) if k == "Square")
    # hover cursors
    cur_body = s.hover(s.vpos(0, 150, 300))
    s.note(f"cursor over a comment edge: {cur_body}")
    s.click(s.vpos(0, 100, 330))
    if s.v.selected != (0, rect_xref):
        s.bad(f"clicking the rectangle's edge did not select it ({s.v.selected})")
    inside = s.v.selected
    s.v.selected = None
    s.click(s.vpos(0, 150, 330))
    if s.v.selected is None:
        s.bad("clicking inside an unfilled rectangle does not select it (only its border does)")
    s.v.selected = inside or (0, rect_xref)
    s.v.viewport().update()
    cur = s.hover(s.vpos(0, 200, 360))
    if cur not in (Qt.SizeFDiagCursor, Qt.SizeBDiagCursor):
        s.bad(f"cursor over the resize handle is {cur}")
    s.drag(s.vpos(0, 200, 360), s.vpos(0, 240, 390))
    r = next(r for k, r, x in s.annots(0) if x == rect_xref)
    if abs(r.x1 - 240) > 3:
        s.bad(f"resize ended at {r}")
    if s.v.selected != (0, rect_xref):
        s.bad("the comment is no longer selected after resizing")
    s.drag(s.vpos(0, 100, 330), s.vpos(0, 130, 350))
    r2 = next(r for k, r, x in s.annots(0) if x == rect_xref)
    if abs(r2.x0 - 130) > 3:
        s.bad(f"move ended at {r2}")
    if s.v.selected != (0, rect_xref):
        s.bad("the comment is no longer selected after moving")
    s.shot("moved")
    # arrow keys nudge the selection (Foxit and every editor do)
    before = next(r for k, r, x in s.annots(0) if x == rect_xref)
    depth = len(s.v.undo_stack)
    s.key(Qt.Key_Right)
    s.key(Qt.Key_Right, Qt.ShiftModifier)
    after = next(r for k, r, x in s.annots(0) if x == rect_xref)
    if abs(after.x0 - before.x0 - 11) > 0.5:
        s.bad(f"Right then Shift+Right moved the comment by {after.x0 - before.x0:.1f} instead of 11")
    if len(s.v.undo_stack) != depth + 1:
        s.bad(f"two arrow-key nudges made {len(s.v.undo_stack) - depth} undo steps")
    if s.v.selected != (0, rect_xref):
        s.bad("the comment is not selected after nudging")
    # right-click menu
    r3 = next(r for k, r, x in s.annots(0) if x == rect_xref)
    items = s.context(s.vpos(0, r3.x0, (r3.y0 + r3.y1) / 2))
    s.note(f"comment menu: {[i.strip() for i in items if not i.startswith('  ')]}")
    # copy / paste
    s.key(Qt.Key_C, Qt.ControlModifier)
    n = len(s.annots(0))
    s.key(Qt.Key_V, Qt.ControlModifier)
    if len(s.annots(0)) != n + 1:
        s.bad(f"Ctrl+V did not paste the copied comment ({s.state()['msg']!r})")
    else:
        new = s.annots(0)[-1]
        if s.v.selected is None or s.v.selected[1] != new[2]:
            s.bad("the pasted comment is not selected")
    # delete
    n = len(s.annots(0))
    s.key(Qt.Key_Delete)
    if len(s.annots(0)) != n - 1:
        s.bad("Delete did not remove the selected comment")
    s.key(Qt.Key_Z, Qt.ControlModifier)
    if len(s.annots(0)) != n:
        s.bad("Ctrl+Z with the page focused did not undo the delete")
    # the line: drag its body, then try its end point
    line_xref = next(x for k, r, x in s.annots(0) if k == "Line")
    s.click(s.vpos(0, 325, 330))
    if s.v.selected != (0, line_xref):
        s.bad(f"clicking the middle of a line does not select it ({s.v.selected})")
    # double-click the typewriter text: Foxit edits it in place
    tw = next(x for k, r, x in s.annots(0) if k == "FreeText")
    asked.clear()
    s.click(s.vpos(0, 105, 426))
    s.double(s.vpos(0, 105, 426))
    if s.v._editor is None:
        s.bad(f"double-clicking typewriter text does not edit it in place (asked {asked})")
    else:
        s.v._editor.setText("Typed note, changed")
        s.click(s.vpos(0, 400, 600))          # clicking elsewhere keeps it
        tw_text = next(a for a in s.v.doc[0].annots() if a.xref == tw).info["content"]
        if tw_text != "Typed note, changed":
            s.bad(f"the typewriter text after editing in place is {tw_text!r}")
    s.key(Qt.Key_Escape)
    if s.v.selected is not None:
        s.bad("Escape did not clear the selection")
    s.shot("end")
    s.close()


@journey
def select_text(path=None, tag="contract"):
    s = Session(f"select-{tag}")
    s.open(path or doc_contract())
    s.v.goto(0)
    app.processEvents()
    words = s.v.doc[0].get_text("words")
    if not words:
        s.tool("select")
        s.drag(s.vpos(0, 72, 100), s.vpos(0, 300, 200))
        st = s.state()
        s.note(f"no text layer; after a drag the message is {st['msg']!r}")
        if "OCR" not in st["msg"]:
            s.bad("a page without text gives no hint to run OCR when selecting text")
        s.tool("highlight")
        s.drag(s.vpos(0, 72, 100), s.vpos(0, 300, 110))
        if "OCR" not in s.state()["msg"]:
            s.bad("highlighting a page without text gives no hint to run OCR")
        s.w.find_box.setText("Acme")
        s.w.do_find()
        s.note(f"find on a scanned page: {s.state()['msg']!r}")
        if "OCR" not in s.state()["msg"]:
            s.bad("Find on a document without text gives no hint to run OCR")
        s.close()
        return
    s.tool("select")
    a, b = words[0], words[min(len(words) - 1, 4)]
    s.drag(s.vpos(0, a[0] + 1, (a[1] + a[3]) / 2), s.vpos(0, b[2] - 1, (b[1] + b[3]) / 2))
    txt = s.v.selected_text()
    s.note(f"selected {len(txt)} characters: {txt[:60]!r}")
    if not txt:
        s.bad("dragging over text with Select selected nothing")
    s.shot("selected")
    items = s.context(s.vpos(0, a[0] + 2, (a[1] + a[3]) / 2))
    s.note(f"text menu: {[i for i in items if not i.startswith('  ')][:12]}")
    s.key(Qt.Key_C, Qt.ControlModifier)
    if QApplication.clipboard().text() != txt:
        s.bad("Ctrl+C did not copy the selected text")
    s.key(Qt.Key_A, Qt.ControlModifier)
    if len(s.v.selected_text()) <= len(txt):
        s.bad("Ctrl+A does not select all text on the page")
    s.key(Qt.Key_Escape)
    if s.v.text_sel:
        s.bad("Escape does not clear the text selection")
    # double-click selects a word, as everywhere else
    s.double(s.vpos(0, (a[0] + a[2]) / 2, (a[1] + a[3]) / 2))
    if s.v.selected_text().strip() != a[4]:
        s.bad(f"double-click does not select the word ({s.v.selected_text()!r} instead of {a[4]!r})")
    # find
    s.w.find_box.setText(a[4])
    s.w.do_find()
    s.note(f"find {a[4]!r}: {s.state()['msg']!r}")
    s.w.find_box.setText("zzzqqq-not-there")
    s.w.do_find()
    s.note(f"find a miss: {s.state()['msg']!r}")
    s.close()


@journey
def scanned():
    select_text(doc_scanned(), "scanned")
    edit = Session("scanned-edit")
    edit.open(doc_scanned())
    edit.tool("edit-text")
    edit.click(edit.vpos(0, 100, 106))
    if "OCR" not in edit.state()["msg"]:
        edit.bad("Edit Text on a scanned page gives no hint to run OCR")
    edit.close()


@journey
def ocr_scan():
    """OCR a scanned document from the window, with progress, then find and select its text."""
    s = Session("ocr")
    v = s.open(doc_scanned())
    answers["text"] = "en"
    t0 = time.time()
    seen = []
    dlg, progress = s.w._progress("OCR")
    s.w._ocr_run(False, ["en"], lambda n, total: (seen.append((n, total)), progress(n, total)))
    dlg.close()
    s.note(f"OCR of {v.doc.page_count} pages: {time.time() - t0:.1f} s, progress calls {seen[:3]}…, msg {s.state()['msg']!r}")
    if not seen:
        s.bad("OCR showed no progress")
    s.w.find_box.setText("Acme")
    s.w.do_find()
    if not v.hits:
        s.bad(f"after OCR, Find does not find 'Acme' ({s.state()['msg']!r})")
    s.shot("found")
    s.w.do_find()
    s.note(f"Enter again in Find: {s.state()['msg']!r}")
    answers["text"] = "Journey text"
    s.close()


@journey
def clipboard_across():
    """Copy a comment and an image in one document, paste both into another, at the mouse."""
    s = Session("clip")
    a = s.open(doc_images())
    a.set_zoom(1.0)
    a.goto(0)
    s.w.apply("box", lambda d: run_cmd("Comment.Rectangle", d, 1, (330, 400, 430, 450)))
    s.tool("hand")
    s.click(s.vpos(0, 330, 425))
    s.key(Qt.Key_C, Qt.ControlModifier)
    s.note(f"copy comment: {s.state()['msg']!r}")
    b = s.open(doc_contract())
    b.set_zoom(1.0)
    b.goto(0)
    app.processEvents()
    QCursor_pos = s.vpos(0, 300, 600)
    from PySide6.QtGui import QCursor
    QCursor.setPos(b.viewport().mapToGlobal(QCursor_pos.toPoint()))
    n = len(s.annots(0))
    s.key(Qt.Key_V, Qt.ControlModifier)
    if len(s.annots(0)) != n + 1:
        s.bad(f"pasting a comment into another document did nothing ({s.state()['msg']!r})")
    else:
        r = s.annots(0)[-1][1]
        s.note(f"pasted comment at {r} (mouse at 300,600)")
        if b.selected is None:
            s.bad("the pasted comment is not selected")
    s.w.docs.setCurrentWidget(a)
    app.processEvents()
    s.tool("edit-object")
    img = next(o for o in a.page_objects(0) if o.kind == "image")
    c = img.rect.tl + (img.rect.br - img.rect.tl) / 2
    s.click(s.vpos(0, c.x, c.y))
    s.key(Qt.Key_C, Qt.ControlModifier)
    s.w.docs.setCurrentWidget(b)
    app.processEvents()
    objs = len(b.page_objects(0))
    s.key(Qt.Key_V, Qt.ControlModifier)
    if len(b.page_objects(0)) <= objs:
        s.bad(f"pasting an image into another document did nothing ({s.state()['msg']!r})")
    elif not b.obj_sel:
        s.bad("the pasted image is not selected")
    s.shot("pasted")
    s.close()


@journey
def redact_flow():
    s = Session("redact")
    v = s.open(doc_contract())
    v.set_zoom(1.0)
    v.goto(0)
    s.tool("select")
    words = v.doc[0].get_text("words")
    mail = next(w for w in words if "@" in w[4])
    s.drag(s.vpos(0, mail[0] + 1, (mail[1] + mail[3]) / 2), s.vpos(0, mail[2] - 1, (mail[1] + mail[3]) / 2))
    items = s.context(s.vpos(0, mail[0] + 3, (mail[1] + mail[3]) / 2))
    if "Mark for Redaction" not in items:
        s.bad(f"no Mark for Redaction in the text menu: {items}")
    v._emit(tool="redact-rects", page=1, rects=v._sel_rects())
    s.note(f"after marking: {s.state()['msg']!r}")
    s.w.apply_redactions()
    txt = v.doc[0].get_text()
    if "jane.doe" in txt:
        s.bad("the e-mail address is still in the text after Apply Redactions")
    s.shot("redacted")
    s.close()


@journey
def links():
    """Hand on a link: pointer cursor, says where it goes, click follows it, Alt+Left comes back."""
    for path, src_page, tag in ((manual(), 3, "manual"), (web("attention-paper.pdf"), 1, "paper")):
        if not path:
            continue
        s = Session(f"links-{tag}")
        v = s.open(path)
        v.goto(src_page)
        app.processEvents()
        s.tool("hand")
        page = v.doc[src_page]
        ln = next(l for l in page.get_links() if l["kind"] in (pymupdf.LINK_GOTO, pymupdf.LINK_NAMED))
        r = pymupdf.Rect(ln["from"])
        c = s.vpos(src_page, (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
        cur = s.hover(c)
        if cur != Qt.PointingHandCursor:
            s.bad(f"cursor over a link is {cur}")
        s.note(f"hover says {s.state()['msg']!r}")
        before = v.verticalScrollBar().value()
        s.click(c)
        target = v._link_target(ln)
        s.note(f"clicked: now on page {v.current_page() + 1}, link target page {target[0] + 1}")
        if v.current_page() != target[0]:
            s.bad(f"clicking a link went to page {v.current_page() + 1} instead of {target[0] + 1}")
        s.shot("followed")
        s.key(Qt.Key_Left, Qt.AltModifier)
        if v.verticalScrollBar().value() != before:
            s.bad("Alt+Left did not return to where the link was")
        s.close()


@journey
def navigate(path=None, tag="manual"):
    path = path or manual() or web("tracemonkey.pdf")
    if not path:
        return
    s = Session(f"nav-{tag}")
    v = s.open(path)
    s.shot("open")
    n = v.doc.page_count
    v.setFocus()
    for k, name in ((Qt.Key_PageDown, "PageDown"), (Qt.Key_End, "End"), (Qt.Key_Home, "Home"), (Qt.Key_Down, "Down"),
                    (Qt.Key_Space, "Space")):
        before = v.verticalScrollBar().value()
        s.key(k)
        after = v.verticalScrollBar().value()
        s.note(f"{name}: scroll {before} -> {after}, page {v.current_page() + 1}/{n}")
        if after == before and not (name == "Home" and before == 0):
            s.bad(f"{name} does not scroll the document")
    s.key(Qt.Key_Home, Qt.ControlModifier)
    if v.verticalScrollBar().value() != 0:
        s.bad("Ctrl+Home does not go to the first page")
    s.key(Qt.Key_End, Qt.ControlModifier)
    if v.current_page() != n - 1:
        s.bad("Ctrl+End does not go to the last page")
    s.key(Qt.Key_Home, Qt.ControlModifier)
    # page spin
    s.w.page_spin.setValue(min(5, n))
    s.w.page_spin.editingFinished.emit()
    app.processEvents()
    if v.current_page() != min(5, n) - 1:
        s.bad(f"typing a page number goes to page {v.current_page() + 1}")
    # Ctrl+wheel zoom
    z = v.zoom
    t0 = time.time()
    s.wheel(QPointF(300, 300), 120, Qt.ControlModifier)
    s.note(f"ctrl+wheel zoom {z:.2f} -> {v.zoom:.2f} in {time.time() - t0:.2f} s")
    s.wheel(QPointF(300, 300), -120, Qt.ControlModifier)
    # bookmarks panel
    s.w._show_nav(1)
    app.processEvents()
    bm = s.w.bookmarks
    count = bm.topLevelItemCount()
    s.note(f"bookmarks: {count} top level")
    if count:
        item = bm.topLevelItem(min(3, count - 1))
        bm.itemClicked.emit(item, 0) if hasattr(bm, "itemClicked") else None
        app.processEvents()
        s.note(f"bookmark '{item.text(0)[:30]}' -> page {v.current_page() + 1}")
    s.w._show_nav(0)
    app.processEvents()
    s.shot("thumbs")
    # zoom extremes and timing of a full re-render
    for z in (0.25, 4.0, 1.0):
        t0 = time.time()
        v.set_zoom(z)
        s.shot(f"zoom{int(z * 100)}")
        s.note(f"zoom {z}: {time.time() - t0:.2f} s with render")
    s.close()


@journey
def edit_text(path=None, tag="contract"):
    s = Session(f"edittext-{tag}")
    s.open(path or doc_contract())
    v = s.v
    v.goto(1)
    app.processEvents()
    s.tool("edit-text")
    words = v.doc[1].get_text("words")
    w = next((w for w in words if w[4].startswith("Payment")), words[2] if len(words) > 2 else None)
    if not w:
        s.bad("no text to edit")
        return
    pos = s.vpos(1, w[0] + 3, (w[1] + w[3]) / 2)
    s.hover(pos)
    if v._hover_line is None:
        s.bad("hovering a text line with Edit Text shows no box")
    s.click(pos)
    if v._editor is None:
        s.bad("clicking a line with Edit Text opened no editor")
        return
    s.shot("editor")
    ed = v._editor
    line_view = v.page_rect_to_view(1, v._edit_target["rect"])
    if abs(ed.geometry().y() - line_view.y()) > 6:
        s.bad(f"editor at y={ed.geometry().y()} but the line is at {line_view.y():.0f}")
    s.key(Qt.Key_End)
    s.type_text(" extra")
    s.key(Qt.Key_Return)
    txt = v.doc[1].get_text()
    if "extra" not in txt:
        s.bad("typing in the inline editor and pressing Enter did not change the text")
    s.shot("edited")
    s.key(Qt.Key_Z, Qt.ControlModifier)
    if "extra" in v.doc[1].get_text():
        s.bad("Ctrl+Z did not undo the text edit")
    # Escape cancels
    s.click(pos)
    if v._editor:
        v._editor.setText("CANCELLED")
        s.key(Qt.Key_Escape)
        if "CANCELLED" in v.doc[1].get_text():
            s.bad("Escape kept the edit")
    s.close()


@journey
def edit_object(path=None, tag="images"):
    s = Session(f"editobj-{tag}")
    s.open(path or doc_images())
    v = s.v
    v.set_zoom(1.0)
    v.goto(0)
    app.processEvents()
    s.tool("edit-object")
    objs = v.page_objects(0)
    s.note(f"objects on page 1: {[(o.kind, tuple(round(c) for c in o.rect)) for o in objs][:8]}")
    img = next((o for o in objs if o.kind == "image"), None)
    if img:
        c = img.rect.tl + (img.rect.br - img.rect.tl) / 2
        cur = s.hover(s.vpos(0, c.x, c.y))
        if cur != Qt.SizeAllCursor:
            s.bad(f"cursor over an image in Edit Object is {cur}")
        s.drag(s.vpos(0, c.x, c.y), s.vpos(0, c.x + 40, c.y + 30))
        moved = next(o for o in v.page_objects(0) if o.kind == "image")
        if abs(moved.rect.x0 - (img.rect.x0 + 40)) > 2:
            s.bad(f"image moved to {moved.rect} instead of +40")
        if not v.obj_sel:
            s.bad("the image is not selected after moving it")
        s.shot("image-moved")
        br = moved.rect.br
        s.drag(s.vpos(0, br.x, br.y), s.vpos(0, br.x - 50, br.y - 50))
        r = next(o for o in v.page_objects(0) if o.kind == "image").rect
        ratio_before, ratio_after = img.rect.width / img.rect.height, r.width / r.height
        if abs(ratio_before - ratio_after) > 0.02:
            s.bad(f"resizing an image changed its aspect ratio {ratio_before:.2f} -> {ratio_after:.2f}")
        s.shot("image-resized")
        items = s.context(s.vpos(0, r.x0 + 10, r.y0 + 10))
        s.note(f"object menu: {[i for i in items if not i.startswith('  ')]}")
        s.key(Qt.Key_C, Qt.ControlModifier)
        n = len(v.page_objects(0))
        s.key(Qt.Key_V, Qt.ControlModifier)
        if len(v.page_objects(0)) <= n:
            s.bad(f"Ctrl+V did not paste the image ({s.state()['msg']!r})")
        s.key(Qt.Key_Delete)
        if len(v.page_objects(0)) != n:
            s.bad("Delete did not remove the pasted image")
        s.key(Qt.Key_Right) if v.obj_sel else None
    shape = next((o for o in v.page_objects(0) if o.kind in ("path", "shape", "vector")), None)
    if shape:
        c = shape.rect.tl + (shape.rect.br - shape.rect.tl) / 2
        s.click(s.vpos(0, c.x, c.y))
        if not v.obj_sel:
            s.bad("clicking a vector shape in Edit Object does not select it")
    text = next((o for o in v.page_objects(0) if o.kind == "text"), None)
    if text:
        c = text.rect.tl + (text.rect.br - text.rect.tl) / 2
        s.click(s.vpos(0, c.x, c.y))
        if not v.obj_sel:
            s.bad("clicking text in Edit Object does not select it")
        asked.clear()
        s.double(s.vpos(0, c.x, c.y))
        s.note(f"double-click on a text object: editor={v._editor is not None} tool={s.w.tool} asked={asked}")
        if v._editor is None:
            s.bad("double-clicking a text object in Edit Object does not start editing its text")
    s.shot("end")
    s.close()


@journey
def hand_picks_added(path=None, tag="contract"):
    """Add Text and Add Image, then move them straight away with Hand."""
    s = Session(f"added-{tag}")
    s.open(path or doc_contract())
    v = s.v
    v.set_zoom(1.0)
    v.goto(0)
    app.processEvents()
    s.tool("add-text")
    s.click(s.vpos(0, 300, 500))
    if s.v._editor is not None:
        s.type_text("Added by hand")
        s.click(s.vpos(0, 100, 700))           # clicking elsewhere keeps it
    st = s.state()
    s.note(f"after Add Text: tool={st['tool']} obj={st['obj']} msg={st['msg']!r}")
    if "Added by hand" not in v.doc[0].get_text():
        s.bad("Add Text placed nothing")
    if not v.obj_sel:
        s.bad("the added text is not selected afterwards")
    s.tool("hand")
    o = next((o for o in v.page_objects(0) if o.added), None)
    if o is None:
        s.bad("the added text is not marked as added")
    else:
        c = o.rect.tl + (o.rect.br - o.rect.tl) / 2
        s.drag(s.vpos(0, c.x, c.y), s.vpos(0, c.x, c.y + 50))
        o2 = next(o for o in v.page_objects(0) if o.added)
        if abs(o2.rect.y0 - (o.rect.y0 + 50)) > 2:
            s.bad(f"Hand did not move the added text ({o.rect} -> {o2.rect})")
    answers["text"] = "Journey text"
    s.shot("end")
    s.close()


@journey
def odd_pages():
    s = Session("odd")
    v = s.open(doc_odd_pages())
    s.shot("open")
    widest = max(w for w, _ in v.sizes)
    if widest > v.viewport().width():
        s.bad("fit width leaves the widest page wider than the view")
    # draw on the rotated page and check the saved coordinates
    v.set_zoom(1.0)
    v.goto(2)
    app.processEvents()
    s.tool("rectangle")
    n = len(s.annots(2))
    a, b = s.vpos(2, 100, 300), s.vpos(2, 200, 360)
    s.drag(a, b)
    res = s.annots(2)
    if len(res) == n:
        s.bad("drawing on the rotated page made nothing")
    else:
        r = res[-1][1]
        if abs(r.x0 - 100) > 4 or abs(r.y0 - 300) > 4:
            s.bad(f"rectangle on the rotated page landed at {r} instead of (100,300,200,360)")
    s.shot("rotated")
    v.goto(3)
    app.processEvents()
    v.fit_page()
    app.processEvents()
    if v.sizes[3][1] > v.viewport().height():
        s.bad("Fit Page on the A3 page leaves it taller than the view")
    s.shot("a3-fit")
    s.close()


@journey
def forms(path=None):
    path = path or web("fw9-form.pdf")
    if not path:
        return
    s = Session("forms")
    v = s.open(path)
    v.set_zoom(1.0)
    app.processEvents()
    s.tool("hand")
    page = v.doc[0]
    widgets = list(page.widgets())
    s.note(f"{len(widgets)} fields on page 1: {[w.field_type_string for w in widgets][:8]}")
    text_field = next((w for w in widgets if w.field_type == pymupdf.PDF_WIDGET_TYPE_TEXT), None)
    if text_field:
        c = text_field.rect.tl + (text_field.rect.br - text_field.rect.tl) / 2
        cur = s.hover(s.vpos(0, c.x, c.y))
        s.note(f"cursor over a text field with Hand: {cur}")
        if cur not in (Qt.IBeamCursor, Qt.PointingHandCursor):
            s.bad(f"the cursor over a form field does not show it can be filled ({cur})")
        asked.clear()
        s.click(s.vpos(0, c.x, c.y))
        if v._editor is None:
            s.bad(f"clicking a text field opened no editor on the field (asked {asked})")
        else:
            s.type_text("Jane Field")
            s.shot("typing-field")
            s.key(Qt.Key_Tab)
            val = next(w for w in v.doc[0].widgets() if w.xref == text_field.xref).field_value
            if val != "Jane Field":
                s.bad(f"typing into a text field and pressing Tab did not set it (value {val!r})")
            nxt = v._edit_target
            if v._editor is None or nxt is None or nxt.get("xref") == text_field.xref:
                s.bad("Tab did not move on to the next field")
            else:
                s.type_text("Second field")
                s.key(Qt.Key_Return)
                val2 = next(w for w in v.doc[nxt["page"]].widgets() if w.xref == nxt["xref"]).field_value
                if val2 != "Second field":
                    s.bad(f"the second field holds {val2!r}")
            if len(v.undo_stack) < 2:
                s.bad("filling two fields is not two undo steps")
    check = next((w for w in widgets if w.field_type == pymupdf.PDF_WIDGET_TYPE_CHECKBOX), None)
    if check:
        c = check.rect.tl + (check.rect.br - check.rect.tl) / 2
        asked.clear()
        before = check.field_value
        s.click(s.vpos(0, c.x, c.y))
        after = next(w for w in v.doc[0].widgets() if w.xref == check.xref).field_value
        s.note(f"checkbox {before!r} -> {after!r}, asked {asked}")
        if after == before:
            s.bad("clicking a checkbox does not toggle it")
        elif asked:
            s.bad("clicking a checkbox opens a dialog instead of just toggling it")
    s.shot("filled")
    answers["text"] = "Journey text"
    s.close()


@journey
def pages_panel():
    s = Session("pages")
    v = s.open(doc_contract())
    s.w._show_nav(0)
    app.processEvents()
    t = s.w.thumbs
    v.goto(3)
    app.processEvents()
    cur = t.currentRow()
    s.note(f"thumbnail row highlighted while on page 4: {cur}")
    if cur != 3:
        s.bad("the thumbnails panel does not follow the current page")
    t.item(1).setSelected(True)
    t.item(2).setSelected(True)
    menus.clear()
    t.customContextMenuRequested.emit(t.visualItemRect(t.item(1)).center())
    s.note(f"thumbnail menu: {menus[-1] if menus else None}")
    s.w._page_command("rotate-right", [1, 2])
    app.processEvents()
    if v.doc[1].rotation != 90:
        s.bad("rotating selected pages from the panel did nothing")
    s.shot("rotated")
    s.w._reorder([0, 2, 1, 3, 4, 5])
    app.processEvents()
    s.note(f"after reorder, page 2 text: {v.doc[1].get_text()[:20]!r}")
    s.w.undo()
    s.w.undo()
    if v.doc[1].rotation != 0:
        s.bad("two undos did not restore order and rotation")
    s.close()


@journey
def tabs():
    s = Session("tabs")
    a = s.open(doc_contract())
    a.set_zoom(1.5)
    a.goto(3)
    b = s.open(doc_images())
    s.tool("edit-object")
    s.w.docs.setCurrentWidget(a)
    app.processEvents()
    if abs(a.zoom - 1.5) > 0.01 or a.current_page() != 3:
        s.bad(f"switching tabs lost the zoom or page ({a.zoom:.2f}, page {a.current_page() + 1})")
    if s.w.page_spin.value() != 4:
        s.bad(f"status bar shows page {s.w.page_spin.value()} for a tab on page 4")
    s.w.docs.setCurrentWidget(b)
    app.processEvents()
    s.note(f"title with images tab: {s.w.windowTitle()!r}")
    s.w.apply("x", lambda d: d[0].insert_text((10, 10), "x"))
    if "*" not in s.w.docs.tabText(s.w.docs.currentIndex()):
        s.bad("a modified document's tab shows no mark")
    asked.clear()
    s.w.close_tab(s.w.docs.currentIndex())
    if not any("Save changes" in q or "save" in q.lower() for q in asked):
        s.bad(f"closing a modified tab did not ask to save ({asked})")
    s.close()


@journey
def protected():
    s = Session("protected")
    d = pymupdf.open(doc_contract())
    p = os.path.join(TMP, "locked.pdf")
    d.save(p, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="u", owner_pw="o",
           permissions=pymupdf.PDF_PERM_PRINT | pymupdf.PDF_PERM_COPY)
    answers["text"] = "u"
    asked.clear()
    v = s.w.open_path(p)
    s.note(f"opened with the user password: readonly={v.readonly}, asked {asked}")
    s.tool("rectangle")
    asked.clear()
    s.drag(s.vpos(0, 100, 300), s.vpos(0, 200, 360))
    s.note(f"drawing on a read-only document: asked {asked}")
    if len(asked) != 1:
        s.bad(f"a read-only document should say once why it cannot be changed ({asked})")
    answers["text"] = "Journey text"
    s.close()


@journey
def arabic_ui():
    from pdfdesk import lang
    lang.install(app, "ar")
    try:
        s = Session("arabic")
        v = s.open(web("arabic.pdf") or doc_contract())
        s.shot("open")
        s.tool("highlight")
        words = v.doc[0].get_text("words")
        if words:
            w = words[0]
            s.drag(s.vpos(0, w[0] + 1, (w[1] + w[3]) / 2), s.vpos(0, w[2] - 1, (w[1] + w[3]) / 2))
            s.note(f"highlight in Arabic UI: {[a[0] for a in s.annots(0)]}, msg {s.state()['msg']!r}")
        s.shot("highlight")
        s.close()
    finally:
        lang.install(app, "en")


@journey
def big_document():
    src = manual()
    if not src:
        return
    d = pymupdf.open(src)
    big = pymupdf.open()
    for _ in range(4):
        big.insert_pdf(d)
    p = os.path.join(TMP, "big.pdf")
    big.save(p)
    s = Session("big")
    t0 = time.time()
    v = s.open(p)
    s.note(f"{v.doc.page_count} pages opened in {time.time() - t0:.2f} s")
    for z in (1.5, 3.0):
        t0 = time.time()
        v.set_zoom(z)
        app.processEvents()
        s.w.grab()
        dt = time.time() - t0
        s.note(f"zoom {z}: {dt:.2f} s")
        if dt > 0.6:
            s.bad(f"zooming a {v.doc.page_count}-page document to {z} takes {dt:.1f} s")
    t0 = time.time()
    for _ in range(40):
        v.verticalScrollBar().setValue(v.verticalScrollBar().value() + v.viewport().height())
        v.viewport().repaint()
    dt = time.time() - t0
    s.note(f"40 screens scrolled in {dt:.2f} s, cache {sum(c.sizeInBytes() for c in v._cache.values()) // 2**20} MB")
    t0 = time.time()
    s.w.apply("note", lambda d: d[0].add_text_annot((50, 50), "n"))
    dt = time.time() - t0
    s.note(f"one edit (undo snapshot of the whole document) took {dt:.2f} s")
    if dt > 1:
        s.bad(f"a single edit on a {v.doc.page_count}-page document takes {dt:.1f} s")
    s.close()


@journey
def web_documents():
    """Every downloaded document: open, fit, draw, select, edit text, Edit Object, save."""
    for name in sorted(os.listdir(os.path.join(CORPUS, "web"))) if os.path.isdir(os.path.join(CORPUS, "web")) else []:
        path = os.path.join(CORPUS, "web", name)
        s = Session(f"web-{os.path.splitext(name)[0]}")
        try:
            v = s.open(path)
        except Exception as e:  # noqa: BLE001
            s.bad(f"could not open: {e}")
            continue
        s.shot("open")
        v.set_zoom(1.0)
        v.goto(0)
        app.processEvents()
        pr = v.doc[0].rect
        s.tool("rectangle")
        n = len(s.annots(0))
        s.drag(s.vpos(0, pr.width * 0.3, pr.height * 0.3), s.vpos(0, pr.width * 0.5, pr.height * 0.4))
        if len(s.annots(0)) <= n:
            s.bad(f"could not draw a rectangle ({s.state()['msg']!r} {asked[-2:]})")
        words = v.doc[0].get_text("words")
        if words:
            s.tool("highlight")
            w = words[len(words) // 2]
            n = len(s.annots(0))
            s.drag(s.vpos(0, w[0] + 0.5, (w[1] + w[3]) / 2), s.vpos(0, w[2] - 0.5, (w[1] + w[3]) / 2))
            if len(s.annots(0)) <= n:
                s.bad(f"could not highlight the word {w[4]!r}")
            s.tool("edit-text")
            s.click(s.vpos(0, w[0] + 0.5, (w[1] + w[3]) / 2))
            s.note(f"edit text on {w[4]!r}: editor={v._editor is not None}")
            if v._editor is not None:
                v._editor.setText(v._editor.text() + "X")
                asked.clear()
                v._commit_editor()
                if asked:
                    s.bad(f"editing a line failed: {asked}")
        s.tool("edit-object")
        objs = v.page_objects(0)
        s.note(f"{len(objs)} objects on page 1")
        s.shot("edited")
        asked.clear()
        ok = s.w.save_as()
        if not ok or asked:
            s.bad(f"save as failed ({asked})")
        s.close()


# ---- run --------------------------------------------------------------------------------------------------------
if __name__ == "__main__":
    names = sys.argv[2:] or list(JOURNEYS)
    for n in names:
        print(f"== {n}", flush=True)
        try:
            JOURNEYS[n]()
        except Exception:  # noqa: BLE001
            import traceback
            print(f"!! {n}: crashed\n{traceback.format_exc()}", flush=True)
    print(f"screenshots in {OUT}", flush=True)
    os._exit(0)          # dozens of windows tear down in random order at interpreter exit; the app itself exits cleanly
