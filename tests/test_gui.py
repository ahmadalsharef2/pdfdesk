import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QInputDialog, QMessageBox

from pdfdesk.commands import run as run_cmd
from pdfdesk.core import security as sec
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

    run_cmd("Sign.CreateID", str(tmp_path / "t.pfx"), "GUI Tester", "pw")
    monkeypatch.setattr(dialogs.DigitalSignDialog, "ask", staticmethod(lambda *a, **k: {
        "pfx": str(tmp_path / "t.pfx"), "password": "pw", "reason": "ok", "location": None, "certify": None,
        "invisible": False}))
    out = str(tmp_path / "s.pdf")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (out, "")))
    w.on_tool({"tool": "digital-sign", "page": 6, "rect": pymupdf.Rect(300, 700, 500, 760), "point": pymupdf.Point(300, 700)})
    res = run_cmd("Sign.Validate", out, trusted_pfx=[(str(tmp_path / "t.pfx"), "pw")])
    assert res and res[0]["valid"] and res[0]["intact"]


def test_save_keeps_password(tmp_path, monkeypatch):
    _app()
    d = pymupdf.open()
    d.new_page().insert_text((72, 72), "hello")
    p = str(tmp_path / "e.pdf")
    d.save(p, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="u", owner_pw="o",
           permissions=sec.permissions(allow_print=False))
    w = Main()
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("o", True)))
    v = w.open_path(p)
    assert v is not None and not v.readonly and v.security.owner_pw == "o"
    # the open password is unknown, so saving asks for it
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("u", True)))
    w.apply("note", lambda d: d[0].add_text_annot((50, 50), "n"))
    assert w.save()
    assert pymupdf.open(p).needs_pass


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


def test_auto_redact_from_the_window(v1_path, monkeypatch):
    _app()
    w = Main()
    v = w.open_path(v1_path)

    def fake_exec(d):
        d.search()
        d.apply_now = True
        d._accept()
        return QDialog.Accepted
    monkeypatch.setattr(dialogs.AutoRedactDialog, "exec", fake_exec)
    w.auto_redact()
    assert all("jane.doe" not in p.get_text() and "555-0142" not in p.get_text() for p in v.doc)
    w.undo()
    w.undo()
    assert "jane.doe" in v.doc[0].get_text()


def test_window_in_arabic_is_right_to_left():
    app = _app()
    from pdfdesk import lang
    lang.install(app, "ar")
    try:
        w = Main()
        assert app.layoutDirection() == Qt.RightToLeft
        assert w.ribbon.bar.tabText(0) == "ملف"
    finally:
        lang.install(app, "en")


def test_file_manager_combine_and_convert(tmp_path, monkeypatch):
    """Two launches (Explorer starts one per file) end in one Combine dialog; Convert opens an image as a PDF."""
    from conftest import make_contract
    _app()
    w = Main()
    a, b = str(tmp_path / "b.pdf"), str(tmp_path / "a.pdf")
    make_contract(a)
    make_contract(b)
    asked = []
    monkeypatch.setattr(dialogs.CombineDialog, "ask", staticmethod(lambda parent, paths: asked.append(paths) or paths))
    w.receive("combine", [a])
    w.receive("combine", [b])
    w._run_batch()                                  # what the timer does once no more launches arrive
    assert asked == [[b, a]]                        # one dialog, sorted by name
    assert w.cur().doc.page_count == 12 and w.cur().modified
    png = str(tmp_path / "scan.png")
    pymupdf.open(a)[0].get_pixmap(dpi=50).save(png)
    w.receive("convert", [png])
    w._run_batch()
    assert w.docs.tabText(w.docs.currentIndex()).startswith("scan.pdf") and w.cur().doc.page_count == 1


def test_fit_follows_the_window_size(v1_path):
    """Fit Width / Fit Page stay fitted when the window changes size; an explicit zoom ends them."""
    app = _app()
    w = Main()
    w.resize(1000, 700)
    w.show()
    v = w.open_path(v1_path)
    app.processEvents()
    assert v.fit_mode == "width"
    assert v.horizontalScrollBar().maximum() == 0                  # the page is never wider than the view
    z1 = v.zoom
    w.resize(1500, 900)
    app.processEvents()
    assert v.fit_mode == "width" and v.zoom > z1 * 1.3
    assert abs(v.zoom - v.fit_zoom("width")) < 1e-9
    assert v.horizontalScrollBar().maximum() == 0 and v.verticalScrollBar().value() == 0
    v.fit_page()
    app.processEvents()
    assert v.fit_mode == "page" and v.sizes[0][1] <= v.viewport().height() - 2 * v.GAP
    w.resize(1000, 700)
    app.processEvents()
    assert v.fit_mode == "page" and v.sizes[0][1] <= v.viewport().height() - 2 * v.GAP
    v.set_zoom(1.0)
    assert v.fit_mode is None and v.zoom == 1.0
    w.resize(1500, 900)
    app.processEvents()
    assert v.zoom == 1.0


def test_zoom_keeps_the_point_under_the_mouse(v1_path):
    app = _app()
    w = Main()
    w.resize(1000, 700)
    w.show()
    v = w.open_path(v1_path)
    app.processEvents()
    v.set_zoom(1.0)
    v.goto(2)
    v.verticalScrollBar().setValue(v.verticalScrollBar().value() + 150)
    anchor = QPointF(v.viewport().width() / 2, 200)              # mid-page: the view can scroll to keep it
    before = v.view_to_page(anchor)
    v.set_zoom(2.0, anchor=anchor)
    after = v.view_to_page(anchor)
    assert before[0] == after[0] and abs(before[1].x - after[1].x) < 1.5 and abs(before[1].y - after[1].y) < 1.5
    v.verticalScrollBar().setValue(0)                              # at the top of the document: stays there
    v.set_zoom(3.0)
    assert v.verticalScrollBar().value() == 0


def test_new_document_can_be_edited(v1_path):
    """A document made by Combine or Convert has no file yet; editing it must work like any other."""
    _app()
    w = Main()
    w.new_doc(pymupdf.open(v1_path), "new.pdf")
    v = w.cur()
    assert not v.readonly and v.security is None and w.docs.tabText(w.docs.currentIndex()).startswith("new.pdf")
    w.apply("Delete", lambda d: d.delete_page(0))
    assert v.doc.page_count == 5 and v.modified


def test_no_window_attribute_hides_a_method():
    """`self.split = QSplitter()` once hid the Split command, so its button called the splitter and crashed."""
    import inspect
    _app()
    w = Main()
    methods = {n for n, f in inspect.getmembers(Main, inspect.isfunction)}
    hidden = sorted(n for n in methods if n in vars(w))
    assert hidden == []


def test_tr_takes_a_value_named_text():
    from pdfdesk.lang import tr
    assert tr("Find “{text}”", text="abc") == "Find “abc”"


def test_typewriter_is_typed_on_the_page_and_selected(v1_path):
    app = _app()
    w = Main()
    v = w.open_path(v1_path)
    w.show()
    app.processEvents()
    v.set_zoom(1.0)
    w.set_tool("typewriter")
    x, y = v._origin(0)
    _mouse(v, "press", (x + 100, y + 400))
    _mouse(v, "release", (x + 100, y + 400))
    assert v._editor is not None                         # no dialog: an editor on the page
    v._editor.setText("Typed here\nsecond line")
    v._commit_editor()
    p0 = v.doc[0]                                        # hold the page: its annotations die with it
    a = next(p0.annots())
    x0, xref = a.rect.x0, a.xref
    assert a.info["content"] == "Typed here\nsecond line" and abs(x0 - 100) < 2
    assert v.selected == (0, xref) and w.tool == "typewriter"
    v.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Right, Qt.NoModifier))
    v.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Right, Qt.NoModifier))
    p0 = v.doc[0]
    assert abs(next(p0.annots()).rect.x0 - (x0 + 2)) < 0.1
    labels = [lab for lab, _ in v.undo_stack]
    assert labels.count("Nudge comment") == 1            # quick nudges are one undo step


def test_form_fields_are_typed_into_and_tab_moves_on(tmp_path):
    app = _app()
    d = pymupdf.open()
    page = d.new_page()
    for n, y in enumerate((100, 140)):
        wd = pymupdf.Widget()
        wd.field_type, wd.field_name, wd.rect = pymupdf.PDF_WIDGET_TYPE_TEXT, f"f{n}", pymupdf.Rect(72, y, 300, y + 20)
        page.add_widget(wd)
    p = str(tmp_path / "form.pdf")
    d.save(p)
    w = Main()
    v = w.open_path(p)
    w.show()
    app.processEvents()
    v.set_zoom(1.0)
    x, y = v._origin(0)
    _mouse(v, "press", (x + 100, y + 110))
    assert v._editor is not None
    v._editor.setValue("first")
    v._commit_editor(1)                                  # Tab
    p0 = v.doc[0]
    assert v._editor is not None and v._edit_target["xref"] != p0.first_widget.xref
    v._editor.setValue("second")
    v._commit_editor()
    p0 = v.doc[0]
    assert [wd.field_value for wd in p0.widgets()] == ["first", "second"]
