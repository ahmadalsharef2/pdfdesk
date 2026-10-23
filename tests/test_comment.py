import pymupdf

from pdfdesk.commands import run


def kinds(doc, page=1):
    pg = doc[page - 1]
    return [a.type[1] for a in pg.annots()]


def test_every_comment_tool(v1, tmp_path):
    for k in ("Highlight", "Underline", "Strikeout", "Squiggly"):
        run(f"Comment.{k}", v1, 1, (72, 105), (160, 112), author="me")
    run("Comment.ReplaceText", v1, 1, (72, 135), (160, 142), "Net 60")
    run("Comment.InsertText", v1, 1, (200, 140), "insert this")
    run("Comment.AreaHighlight", v1, 1, (300, 300, 400, 340))
    run("Comment.Note", v1, 1, (500, 80), "a note")
    f = tmp_path / "att.txt"
    f.write_text("hello")
    run("Comment.File", v1, 1, (520, 80), str(f))
    run("Comment.Typewriter", v1, 1, (72, 400), "typed here")
    run("Comment.Textbox", v1, 1, (72, 450, 250, 490), "box text")
    run("Comment.Callout", v1, 1, (100, 112), (300, 500, 480, 540), "callout text")
    run("Comment.Rectangle", v1, 1, (72, 560, 150, 600))
    run("Comment.Oval", v1, 1, (160, 560, 240, 600))
    run("Comment.Line", v1, 1, (250, 560), (320, 600))
    run("Comment.Arrow", v1, 1, (330, 560), (400, 600))
    run("Comment.Polygon", v1, 1, [(72, 620), (120, 610), (140, 660), (80, 670)])
    run("Comment.Cloud", v1, 1, [(160, 620), (220, 610), (240, 660), (170, 670)])
    run("Comment.Polyline", v1, 1, [(260, 620), (300, 650), (340, 620)])
    run("Comment.Pencil", v1, 1, [[(360, 620), (380, 640), (400, 630)]])
    run("Comment.Stamp", v1, 1, (420, 680, 560, 730), "Approved")
    out = tmp_path / "c.pdf"
    v1.save(out)
    d = pymupdf.open(out)
    got = kinds(d)
    for t in ("Highlight", "Underline", "StrikeOut", "Squiggly", "Caret", "Text", "FileAttachment", "FreeText",
              "Square", "Circle", "Line", "Polygon", "PolyLine", "Ink", "Stamp"):
        assert t in got, t
    p0 = d[0]
    hl = [a for a in p0.annots() if a.type[1] == "Highlight"][0]
    assert hl.info["title"] == "me" and "Client" in p0.get_textbox(hl.rect)
    att = [a for a in p0.annots() if a.type[1] == "FileAttachment"][0]
    assert att.get_file() == b"hello"
    assert len(run("Comment.List", d)) == len(got)


def test_select_and_delete(v1):
    x = run("Comment.Rectangle", v1, 1, (72, 560, 150, 600))
    assert run("Comment.At", v1, 1, (100, 580)) == x
    assert run("Comment.Delete", v1, 1, x)
    p0 = v1[0]
    assert list(p0.annots()) == []
