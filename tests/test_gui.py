import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from pdfdesk.commands import run as run_cmd
from pdfdesk.gui import dialogs
from pdfdesk.gui.app import RIBBON, Main


def _app():
    return QApplication.instance() or QApplication([])


def _mouse(view, kind, pos):
    btn = Qt.LeftButton
    t = {"press": QEvent.MouseButtonPress, "move": QEvent.MouseMove, "release": QEvent.MouseButtonRelease}[kind]
    ev = QMouseEvent(t, QPointF(*pos), QPointF(*pos), btn, btn if kind != "release" else Qt.NoButton, Qt.NoModifier)
    {"press": view.mousePressEvent, "move": view.mouseMoveEvent, "release": view.mouseReleaseEvent}[kind](ev)


def _drag(view, a, b):
    _mouse(view, "press", a)
    _mouse(view, "move", b)
    _mouse(view, "release", b)


def test_window_opens_and_edits(v1_path):
    app = _app()
    w = Main()
    w.open_path(v1_path)
    w.show()
    app.processEvents()
    assert [w.ribbon.bar.tabText(i).replace("&&", "&") for i in range(w.ribbon.bar.count())] == \
        [r.replace("&&", "&") for r in RIBBON]
    v = w.cur()
    assert v.doc.page_count == 6 and v.find("Acme") == 6
    w.apply("Delete", lambda d: d.delete_page(0))
    assert v.doc.page_count == 5
    w.undo()
    assert v.doc.page_count == 6
    w.redo()
    assert v.doc.page_count == 5
    assert not w.grab().isNull()


def test_mouse_drag_creates_comment_and_undo(v1_path):
    app = _app()
    w = Main()
    w.open_path(v1_path)
    w.show()
    app.processEvents()
    v = w.cur()
    v.set_zoom(1.0)
    app.processEvents()
    w.set_tool("rectangle")
    x, y = v._origin(0)
    _drag(v, (x + 100, y + 300), (x + 200, y + 350))
    p0 = v.doc[0]
    kinds = [a.type[1] for a in p0.annots()]
    assert kinds == ["Square"], kinds
    r = list(p0.annots())[0].rect
    assert abs(r.x0 - 100) < 3 and abs(r.y0 - 300) < 3 and abs(r.width - 100) < 4
    w.undo()
    assert list(v.doc[0].annots()) == []


def test_highlight_by_dragging_over_text(v1_path):
    app = _app()
    w = Main()
    w.open_path(v1_path)
    w.show()
    app.processEvents()
    v = w.cur()
    v.set_zoom(1.0)
    app.processEvents()
    w.set_tool("highlight")
    x, y = v._origin(0)
    _drag(v, (x + 74, y + 107), (x + 160, y + 107))   # the "Client: Acme Ltd" line
    p0 = v.doc[0]
    hl = [a for a in p0.annots() if a.type[1] == "Highlight"]
    assert hl and "Client" in p0.get_textbox(hl[0].rect)


def test_edit_text_tool_commit(v1_path):
    app = _app()
    w = Main()
    w.open_path(v1_path)
    w.show()
    app.processEvents()
    v = w.cur()
    v.set_zoom(1.0)
    w.set_tool("edit-text")
    x, y = v._origin(1)
    _mouse(v, "press", (x + 80, y + 137))
    assert v._editor is not None and v._editor.text() == "Payment due net 30 days."
    v._editor.setText("Payment due net 90 days.")
    v._commit_editor()
    assert "net 90 days." in v.doc[1].get_text() and "net 30 days." not in v.doc[1].get_text()


def test_thumbnail_reorder_and_delete(v1_path, monkeypatch):
    app = _app()
    w = Main()
    w.open_path(v1_path)
    w.show()
    app.processEvents()
    assert w.thumbs.count() == 6
    w._reorder([5, 0, 1, 2, 3, 4])
    assert "page 6" in w.cur().doc[0].get_text()
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))  # would block
    w._page_command("delete", [0])
    assert w.cur().doc.page_count == 5 and w.thumbs.count() == 5
    

def test_signature_placement_and_digital_sign(v1_path, tmp_path, monkeypatch):
    app = _app()
    w = Main()
    w.open_path(v1_path)
    w.show()
    app.processEvents()
    v = w.cur()
    w.sig_spec = {"kind": "typed", "name": "Jane Doe"}
    w.on_tool({"tool": "sign-place", "page": 6, "rect": pymupdf.Rect(300, 600, 500, 650), "point": pymupdf.Point(300, 600)})
    assert "Jane Doe" in v.doc[5].get_text()

    pfx = dialogs.IDS.parent / "test.pfx"
    from pdfdesk.commands import run
    run("Sign.CreateID", str(tmp_path / "t.pfx"), "GUI Tester", "pw")
    monkeypatch.setattr(dialogs.DigitalSignDialog, "ask", staticmethod(lambda *a, **k: {
        "pfx": str(tmp_path / "t.pfx"), "password": "pw", "reason": "ok", "location": None, "certify": None,
        "invisible": False}))
    out = str(tmp_path / "s.pdf")
    from PySide6.QtWidgets import QFileDialog
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (out, "")))
    w.on_tool({"tool": "digital-sign", "page": 6, "rect": pymupdf.Rect(300, 700, 500, 760), "point": pymupdf.Point(300, 700)})
    res = run("Sign.Validate", out, trusted_pfx=[(str(tmp_path / "t.pfx"), "pw")])
    assert res and res[0]["valid"] and res[0]["intact"]


def test_save_keeps_password(tmp_path):
    app = _app()
    d = pymupdf.open()
    d.new_page().insert_text((72, 72), "hello")
    p = str(tmp_path / "e.pdf")
    from pdfdesk.core import security as sec
    d.save(p, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="u", owner_pw="o",
           permissions=sec.permissions(allow_print=False))
    w = Main()
    from PySide6.QtWidgets import QInputDialog
    import pytest
    pytest.importorskip("PySide6")
    QInputDialog.getText = staticmethod(lambda *a, **k: ("o", True))
    v = w.open_path(p)
    assert v is not None and not v.readonly and v.security.owner_pw == "o"
    # user password unknown -> would normally prompt; supply it
    QInputDialog.getText = staticmethod(lambda *a, **k: ("u", True))
    w.apply("note", lambda d: d[0].add_text_annot((50, 50), "n"))
    assert w.save()
    re = pymupdf.open(p)
    assert re.needs_pass


def test_edit_text_kept_when_clicking_away(v1_path):
    app = _app()
    w = Main()
    w.open_path(v1_path)
    w.show()
    app.processEvents()
    v = w.cur()
    v.set_zoom(1.0)
    w.set_tool("edit-text")
    x, y = v._origin(1)
    _mouse(v, "press", (x + 80, y + 137))
    v._editor.setText("Payment due net 60 days.")
    w.set_tool("hand")                       # no Enter: switching away keeps the edit
    assert "net 60 days." in v.doc[1].get_text()


def test_signature_select_resize_and_delete(v1_path, tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setattr(dialogs, "SIGNER", tmp_path / "signer.json")
    dialogs.save_signer_profile({"name": "Jane Doe", "company": "Muster GmbH", "show": ["name", "company"]})
    w = Main()
    w.open_path(v1_path)
    w.show()
    app.processEvents()
    v = w.cur()
    v.set_zoom(1.0)
    w.sig_spec = {"kind": "typed", "name": "Jane Doe"}
    w.on_tool({"tool": "sign-place", "page": 6, "rect": pymupdf.Rect(300, 600, 460, 650), "point": pymupdf.Point(300, 600)})
    assert w.tool == "edit-object" and v.obj_sel is not None       # selected right after placing
    i, rect, resizable = v._selection()
    assert resizable and "Muster GmbH" in v.doc[5].get_text(clip=rect)
    v.goto(5)
    br = v.page_rect_to_view(i, rect).bottomRight()
    _drag(v, (br.x(), br.y()), (br.x() - rect.width / 2, br.y() - rect.height / 2))   # corner: half size
    _i, small, _ = v._selection()
    assert abs(small.width - rect.width / 2) < 1 and abs(small.height - rect.height / 2) < 1
    assert abs(small.x0 - rect.x0) < 0.5 and abs(small.y0 - rect.y0) < 0.5
    c = v.page_rect_to_view(i, small).center()
    _drag(v, (c.x(), c.y()), (c.x() - 100, c.y()))                        # body: move
    _i, moved, _ = v._selection()
    assert abs(moved.x0 - (small.x0 - 100)) < 1
    from PySide6.QtGui import QKeyEvent
    v.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Delete, Qt.NoModifier))
    assert "Muster GmbH" not in v.doc[5].get_text()
    w.undo()
    assert "Muster GmbH" in w.cur().doc[5].get_text()


def test_hand_resizes_box_comment(v1_path):
    app = _app()
    w = Main()
    w.open_path(v1_path)
    w.show()
    app.processEvents()
    v = w.cur()
    v.set_zoom(1.0)
    w.apply("box", lambda d: run_cmd("Comment.Rectangle", d, 1, (100, 100, 200, 150)))
    w.set_tool("hand")
    x, y = v._origin(0)
    _mouse(v, "press", (x + 100, y + 125))                                 # on the left edge: selects it
    _mouse(v, "release", (x + 100, y + 125))
    assert v.selected
    _drag(v, (x + 200, y + 150), (x + 260, y + 190))                       # bottom-right handle
    page = v.doc[0]
    r = next(page.annots()).rect
    assert abs(r.x1 - 260) < 3 and abs(r.y1 - 190) < 3 and abs(r.x0 - 100) < 3
