import pymupdf

from pdfdesk.commands import edit, run, search


def test_edit_line_keeps_font_and_position(v1):
    ln = edit.line_at(v1, 2, (80, 137))
    assert ln.text == "Payment due net 30 days."
    run("Text.EditLine", v1, 2, (80, 137), "Payment due net 45 days.")
    texts = [l.text for l in edit.lines(v1, 2)]
    assert "Payment due net 45 days." in texts and "Payment due net 30 days." not in texts
    new = [l for l in edit.lines(v1, 2) if "45" in l.text][0]
    assert abs(new.origin.y - ln.origin.y) < 0.5 and abs(new.origin.x - ln.origin.x) < 0.5
    assert new.size == ln.size and "Helvetica" in new.font
    # neighbouring lines untouched
    assert "Client: Acme Ltd" in texts and any(t.startswith("Contact:") for t in texts)


def test_edit_keeps_users_redaction_marks(v1):
    run("Redact.MarkRects", v1, page=2, rects=[(70, 160, 300, 175)])
    run("Text.EditLine", v1, 2, (80, 137), "changed")
    assert len(list(v1[1].annots(types=[pymupdf.PDF_ANNOT_REDACT]))) == 1


def test_replace_all(v1):
    assert run("Text.Replace", v1, "Acme Ltd", "Acme GmbH") == 6
    assert all("Acme Ltd" not in p.get_text() and "Acme GmbH" in p.get_text() for p in v1)


def test_add_text_latin_and_arabic():
    d = pymupdf.open()
    d.new_page()
    run("Text.Add", d, 1, (72, 100), "Added line")
    run("Text.Add", d, 1, (72, 150), "مرحبا بالعالم")
    assert "Added line" in d[0].get_text()
    assert search.find(d[0], "مرحبا بالعالم")
    assert search.find(d[0], "بالعالم")


def test_edit_real_manual_heading(tmp_path):
    import pathlib
    import pytest
    m = pathlib.Path("tests/corpus/foxit/manual.pdf")
    if not m.exists():
        pytest.skip("Foxit manual not copied locally")
    d = pymupdf.open(m)
    ln = [l for l in edit.lines(d, 323) if l.text == "Mark for Redaction"][0]
    run("Text.EditLine", d, 323, ln.rect.tl + (5, ln.rect.height / 2), "Mark Content for Redaction")
    new = [l for l in edit.lines(d, 323) if l.text == "Mark Content for Redaction"][0]
    assert new.font == ln.font and abs(new.origin.y - ln.origin.y) < 0.5
