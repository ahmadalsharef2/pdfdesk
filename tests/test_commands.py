"""Commands, run headless on a generated contract (see conftest.py)."""
import shutil

import pymupdf
import pytest
from conftest import make_contract

from pdfdesk import lang
from pdfdesk.commands import compare as cmp
from pdfdesk.commands import edit, run, search
from pdfdesk.commands import ocr as ocrmod
from pdfdesk.commands.protect import PATTERNS
from pdfdesk.core import security as sec


# ---- organize ---------------------------------------------------------------------------------------


def texts(d):
    return [p.get_text().split("\n")[0] for p in d]


def test_rotate_delete_reverse(v1):
    run("Pages.Rotate", v1, angle=90, pages="2")
    assert v1[1].rotation == 90 and v1[0].rotation == 0
    run("Pages.Delete", v1, pages="3-4")
    assert v1.page_count == 4
    run("Pages.Reverse", v1)
    assert texts(v1) == ["Contract page 6", "Contract page 5", "Contract page 2", "Contract page 1"]


def test_extract_split_combine(v1, tmp_path, v1_path):
    ex = run("Pages.Extract", v1, pages="2-3")
    assert ex.page_count == 2 and "page 2" in ex[0].get_text()
    parts = run("Pages.Split", v1, by_bookmarks=True)
    assert [n for n, _ in parts] == ["Intro", "Terms", "Signatures"]
    assert sum(d.page_count for _, d in parts) == 6
    c = run("Pages.Combine", [v1_path, v1_path])
    assert c.page_count == 12 and [t[2] for t in c.get_toc()] == [1, 7]


def test_labels(v1):
    run("Pages.Labels", v1, rules=[{"startpage": 0, "style": "r", "firstpagenum": 1},
                                   {"startpage": 6 - 1, "style": "D", "firstpagenum": 1}])
    assert v1[0].get_label() == "i" and v1[5].get_label() == "1"


def test_header_footer_and_bates(v1):
    run("Pages.HeaderFooter", v1, footer=("", "Page <<page>> of <<total>>", "<<bates>>"),
        bates={"prefix": "ABC", "start": 1, "digits": 6})
    t = v1[5].get_text()
    assert "Page 6 of 6" in t and "ABC000006" in t


def test_watermark_toggle(v1):
    run("Pages.Watermark", v1, text="DRAFT")
    assert "DRAFT" in v1[0].get_text()
    run("Pages.RemoveWatermark", v1)
    assert "DRAFT" not in v1[0].get_text()
    assert "Contract page 1" in v1[0].get_text()


# ---- edit -------------------------------------------------------------------------------------------


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


def test_added_text_and_signature_stand_upright_on_a_rotated_page():
    d = pymupdf.open()
    d.new_page(width=400, height=600).set_rotation(90)          # a sideways scan: seen 600 wide, 400 high
    p = d[0]
    seen = pymupdf.Rect(100, 150, 300, 210)                     # where the signature box is on the screen
    run("Text.Add", d, 1, pymupdf.Point(100, 100) * p.derotation_matrix, "Added line")
    run("Sign.Place", d, 1, seen * p.derotation_matrix, {"kind": "typed", "name": "Ahmad"})
    for word in ("Added", "Ahmad"):
        box = pymupdf.Rect(next(w for w in d[0].get_text("words") if w[4] == word)[:4]) * d[0].rotation_matrix
        assert box.width > box.height                           # reads left to right as seen
    assert (seen + (-6, -6, 6, 6)).contains(box)                    # the signature is in its box, flourishes aside


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


# ---- comment ----------------------------------------------------------------------------------------


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


# ---- protect ----------------------------------------------------------------------------------------


def all_stream_bytes(path):
    d = pymupdf.open(path)
    return b"".join(d.xref_stream(x) or b"" for x in range(1, d.xref_length()))


def test_redaction_removes_text_from_file(v1, tmp_path):
    n = run("Redact.Search", v1, needle="Acme Ltd", overlay="[CLIENT]")
    assert n == 6
    run("Redact.Apply", v1)
    out = tmp_path / "r.pdf"
    v1.save(out, garbage=4, clean=True, deflate=True)
    d = pymupdf.open(out)
    assert all("Acme" not in p.get_text() for p in d)
    assert all("[CLIENT]" in p.get_text() for p in d)
    assert b"Acme" not in out.read_bytes() and b"Acme" not in all_stream_bytes(out)


def test_pattern_redaction(v1, tmp_path):
    run("Redact.Search", v1, pattern=r"[\w.]+@[\w.]+\.\w+")
    run("Redact.Apply", v1)
    assert all("jane.doe" not in p.get_text() for p in v1)
    assert all("Payment due" in p.get_text() for p in v1)


def test_encrypt_roundtrip(v1, tmp_path):
    out = str(tmp_path / "e.pdf")
    run("Protect.Encrypt", v1, out=out, user_pw="user1", owner_pw="owner1")
    d = pymupdf.open(out)
    assert d.needs_pass and d.authenticate("user1") and d.page_count == 6


# ---- security ---------------------------------------------------------------------------------------


def _encrypted(path, user="u", owner="o", allow_print=False):
    d = pymupdf.open()
    d.new_page().insert_text((72, 72), "secret text")
    d.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=user, owner_pw=owner,
           permissions=sec.permissions(allow_print=allow_print))


def test_full_save_keeps_protection(tmp_path):
    p = str(tmp_path / "e.pdf")
    _encrypted(p)
    d = pymupdf.open(p)
    auth = d.authenticate("o")
    s = sec.from_open(d, "o", auth)
    assert s.owner_pw == "o" and s.user_pw is None and not s.complete
    with pytest.raises(PermissionError):           # never write an unprotected copy silently
        sec.save(d, p, s, incremental=False)
    s.user_pw = "u"
    out = sec.save(d, p, s, incremental=False)
    re = pymupdf.open(p)
    assert re.needs_pass and re.authenticate("u") == 2
    assert not (re.permissions & pymupdf.PDF_PERM_PRINT)  # print restriction kept
    assert "secret text" in out[0].get_text()


def test_incremental_save_keeps_original_encryption(tmp_path):
    p = str(tmp_path / "e.pdf")
    _encrypted(p)
    d = pymupdf.open(p)
    s = sec.from_open(d, "u", d.authenticate("u"))
    d[0].add_text_annot((50, 50), "note")
    sec.save(d, p, s, incremental=True)
    assert pymupdf.open(p).needs_pass


def test_restricted_when_user_password_only(tmp_path):
    p = str(tmp_path / "e.pdf")
    _encrypted(p)
    d = pymupdf.open(p)
    assert sec.restricted(d, d.authenticate("u"))
    d2 = pymupdf.open(p)
    assert not sec.restricted(d2, d2.authenticate("o"))


def test_remove_security(tmp_path):
    p = str(tmp_path / "e.pdf")
    _encrypted(p)
    d = pymupdf.open(p)
    d.authenticate("o")
    sec.save(d, p, None, incremental=False)
    assert not pymupdf.open(p).needs_pass


def test_save_after_tobytes_keeps_encryption(tmp_path):
    p = str(tmp_path / "e.pdf")
    _encrypted(p)
    d = pymupdf.open(p)
    s = sec.from_open(d, "o", d.authenticate("o"))
    s.user_pw = "u"
    d.tobytes()                      # what every undo checkpoint does
    d[0].add_text_annot((50, 50), "note")
    sec.save(d, p, s, incremental=True)
    assert pymupdf.open(p).needs_pass


def test_save_after_snapshots_keeps_placed_signature(v1_path):
    """Regression: an incremental save after undo snapshots dropped the page's new /Contents (blank page)."""
    from pdfdesk.commands import run
    d = pymupdf.open(v1_path)
    d.tobytes()                                                       # undo checkpoint
    run("Sign.Place", d, 2, (320, 600, 480, 650), {"kind": "typed", "name": "Jane Doe"}, ["Jane Doe"])
    d.tobytes()                                                       # undo checkpoint
    o = run("Object.List", d, 2)[-1]
    run("Object.Transform", d, 2, o.index, o.rect + (10, 10, 10, 10))
    text = d[1].get_text()
    sec.save(d, v1_path, None, incremental=True)
    r = pymupdf.open(v1_path)
    assert r[1].get_text() == text and "Jane Doe" in text and len(r[1].get_text()) > 100


# ---- sign -------------------------------------------------------------------------------------------


def test_visual_signatures(v1, tmp_path):
    run("Sign.Typed", v1, 6, (300, 600, 500, 650), "Jane Doe")
    assert "Jane Doe" in v1[5].get_text()
    run("Sign.Ink", v1, 6, [[(300, 700), (320, 690), (340, 710), (360, 695)]])
    assert v1[5].get_drawings()
    png = tmp_path / "s.png"
    v1[0].get_pixmap(clip=(72, 60, 200, 80)).save(png)
    run("Sign.Image", v1, 6, (300, 740, 400, 780), path=str(png))
    assert v1[5].get_images()


def test_digital_sign_validate_certify(v1_path, tmp_path):
    pfx = str(tmp_path / "me.pfx")
    run("Sign.CreateID", pfx, "Test Signer", "pw123", email="t@example.com")
    out = str(tmp_path / "signed.pdf")
    run("Sign.Digital", v1_path, out, pfx, "pw123", page=6, rect=(300, 600, 520, 660), reason="Approved")
    d = pymupdf.open(out)
    w = [x for x in d[5].widgets()]
    assert len(w) == 1 and w[0].field_type == pymupdf.PDF_WIDGET_TYPE_SIGNATURE
    assert all(abs(a - b) < 1 for a, b in zip(w[0].rect, (300, 600, 520, 660)))
    res = run("Sign.Validate", out, trusted_pfx=[(pfx, "pw123")])
    assert res[0]["intact"] and res[0]["valid"] and res[0]["trusted"] and "Test Signer" in res[0]["signer"]
    assert run("Sign.Validate", out)[0]["trusted"] is False       # self-signed, not in trust list

    # change after signing: incremental comment keeps signature intact but flags the modification
    d.load_page(0).add_text_annot((50, 50), "later")
    d.saveIncr()
    res = run("Sign.Validate", out, trusted_pfx=[(pfx, "pw123")])
    assert res[0]["intact"] and res[0]["modification_level"] != "NONE"

    # certify with "form fill and sign"
    cert = str(tmp_path / "cert.pdf")
    run("Sign.Digital", v1_path, cert, pfx, "pw123", certify="forms")
    r = run("Sign.Validate", cert, trusted_pfx=[(pfx, "pw123")])
    assert r[0]["valid"] and r[0]["docmdp_ok"] is not False


def test_signature_caption(v1):
    import datetime as dt
    from pdfdesk.commands import sign
    prof = {"name": "Jane Doe", "position": "Projektleiterin", "company": "Muster GmbH", "email": "jane@example.com",
            "phone": "+49 30 123456", "address": "Hauptstraße 1, Berlin", "show": ["name", "company", "email", "date"]}
    lines = sign.caption_lines(prof, today=dt.date(2026, 10, 26))
    assert lines == ["Jane Doe", "Muster GmbH", "jane@example.com", "2026-10-26"]   # unticked fields left out
    lines = sign.caption_lines({**prof, "layout": "compact"}, today=dt.date(2026, 10, 26))
    assert lines == ["Jane Doe · Muster GmbH", "jane@example.com · 2026-10-26"]
    assert sign.caption_lines({"show": []}) == []
    r = run("Sign.Caption", v1, 6, (300, 600, 500, 650), lines)
    text = v1[5].get_text(clip=r)
    assert "Muster GmbH" in text and "Hauptstraße" not in text and "+49" not in text
    assert r.y0 == 650 and r.height < 25


def test_placed_signature_is_one_movable_object(v1):
    before = len(run("Object.List", v1, 6))
    box = run("Sign.Place", v1, 6, (300, 600, 460, 650), {"kind": "typed", "name": "Jane Doe"},
              ["Jane Doe", "Muster GmbH"])
    assert box.y0 == 600 and box.y1 > 650                          # caption below the signature, same object
    objs = run("Object.List", v1, 6)
    assert len(objs) == before + 1
    sig = next(o for o in objs if abs(o.rect.y0 - 600) < 0.5 and o.kind == "form")
    run("Object.Transform", v1, 6, sig.index, (100, 700, 180, 700 + box.height / 2))   # move + half size
    moved = next(o for o in run("Object.List", v1, 6) if o.index == sig.index)
    assert abs(moved.rect.x0 - 100) < 0.5 and abs(moved.rect.width - 80) < 0.5
    t = v1[5].get_text(clip=moved.rect)
    assert "Jane Doe" in t and "Muster GmbH" in t
    run("Object.Delete", v1, 6, sig.index)
    assert "Muster GmbH" not in v1[5].get_text()


# ---- convert ----------------------------------------------------------------------------------------


def test_from_image_text_html(tmp_path, v1):
    png = tmp_path / "a.png"
    v1[0].get_pixmap(dpi=72).save(png)
    assert run("Convert.FromFile", str(png)).page_count == 1
    t = tmp_path / "a.txt"
    t.write_text("line one\nline two\n")
    assert "line two" in run("Convert.FromFile", str(t))[0].get_text()
    h = tmp_path / "a.html"
    h.write_text("<h1>Title</h1><p>Body paragraph</p>")
    assert "Body paragraph" in run("Convert.FromFile", str(h))[0].get_text()


@pytest.mark.skipif(not shutil.which("soffice"), reason="LibreOffice not installed")
def test_from_office_and_combine(tmp_path, v1_path):
    from docx import Document
    p = tmp_path / "letter.docx"
    doc = Document()
    doc.add_heading("Letter heading", 1)
    doc.add_paragraph("Dear reader, this came from Word.")
    doc.save(p)
    pdf = run("Convert.FromFile", str(p))
    assert "this came from Word" in pdf[0].get_text()
    c = run("Convert.Combine", [v1_path, str(p)])
    assert c.page_count == 7 and [t[1] for t in c.get_toc() if t[0] == 1][:2] == ["v1", "letter"]


def test_export_formats(tmp_path, v1, v1_path):
    imgs = run("Convert.ToImages", v1, str(tmp_path / "img"), dpi=72, pages="1-2")
    assert len(imgs) == 2 and pymupdf.open(imgs[0])[0].rect.width == 595
    run("Convert.ToText", v1, str(tmp_path / "a.txt"))
    assert "Acme Ltd" in (tmp_path / "a.txt").read_text()
    run("Convert.ToHtml", v1, str(tmp_path / "a.html"))
    assert "Acme Ltd" in (tmp_path / "a.html").read_text()
    run("Convert.ToWord", v1_path, str(tmp_path / "a.docx"))
    from docx import Document
    assert "Acme Ltd" in "\n".join(p.text for p in Document(str(tmp_path / "a.docx")).paragraphs)
    run("Convert.ToExcel", v1, str(tmp_path / "a.xlsx"))
    from openpyxl import load_workbook
    assert load_workbook(tmp_path / "a.xlsx").sheetnames
    run("Convert.ToPowerPoint", v1, str(tmp_path / "a.pptx"))
    from pptx import Presentation
    prs = Presentation(str(tmp_path / "a.pptx"))
    assert len(prs.slides) == 6
    assert "Acme Ltd" in " ".join(s.text_frame.text for s in prs.slides[0].shapes if s.has_text_frame)


def test_pdfa(tmp_path, v1_path):
    out = str(tmp_path / "a.pdf")
    run("Convert.ToPDFA", v1_path, out)
    xmp = pymupdf.open(out).get_xml_metadata()
    assert "pdfaid:part" in xmp and "Acme Ltd" in pymupdf.open(out)[0].get_text()


# ---- compare ocr ------------------------------------------------------------------------------------


def test_compare_finds_known_edits(tmp_path):
    make_contract(tmp_path / "a.pdf", False)
    make_contract(tmp_path / "b.pdf", True)
    old, new = pymupdf.open(tmp_path / "a.pdf"), pymupdf.open(tmp_path / "b.pdf")
    res, changes = run("Compare.Run", old, new)
    kinds = sorted((c.kind, c.new_page if c.new_page is not None else c.old_page) for c in changes)
    assert kinds == [("insert", 2), ("replace", 1)]          # p.3 insertion, p.2 replacement (0-based pages)
    assert cmp.summary(changes)["replace"] == 1 and cmp.summary(changes)["insert"] == 1
    assert res.page_count == 1 + 6
    p2 = res[2]
    assert "Replace: 1" in res[0].get_text() and len(list(p2.annots())) >= 2


def test_compare_identical_has_no_changes(tmp_path):
    make_contract(tmp_path / "a.pdf", False)
    d = pymupdf.open(tmp_path / "a.pdf")
    assert run("Compare.Run", d, d)[1] == []


def test_ocr_makes_scan_searchable(tmp_path):
    src = pymupdf.open()
    p = src.new_page()
    p.insert_text((72, 100), "Invoice number 4711 payable within thirty days", fontsize=14)
    pix = p.get_pixmap(dpi=200, colorspace=pymupdf.csGRAY)
    scan = pymupdf.open()
    sp = scan.new_page(width=p.rect.width, height=p.rect.height)
    sp.insert_image(sp.rect, pixmap=pix)
    scan.save(tmp_path / "scan.pdf")
    s = pymupdf.open(tmp_path / "scan.pdf")
    assert ocrmod.is_scanned(s) and s[0].get_text().strip() == ""
    run("Ocr.Run", str(tmp_path / "scan.pdf"), str(tmp_path / "out.pdf"))
    t = pymupdf.open(tmp_path / "out.pdf")[0].get_text().lower()
    assert "invoice" in t and "4711" in t and "thirty" in t


def _scan_of(page: pymupdf.Page) -> pymupdf.Document:
    """A one-page image-only copy of a page, like a scanner makes."""
    pix = page.get_pixmap(dpi=200, colorspace=pymupdf.csGRAY)
    scan = pymupdf.open()
    scan.new_page(width=page.rect.width, height=page.rect.height).insert_image(page.rect, pixmap=pix)
    return scan


def test_auto_redact_text_and_scan():
    d = pymupdf.open()
    p = d.new_page()
    p.insert_text((72, 100), "Mail jane.doe@example.com, call +49 30 1234567", fontsize=12)
    p.insert_text((72, 130), "IBAN DE89 3704 0044 0532 0130 00, Steuer-ID 86 095 742 719, ref 123456", fontsize=12)
    d.insert_pdf(_scan_of(p))
    found = run("Redact.Find", d, kinds=list(PATTERNS), ocr_scans=True)
    texts = {(f["page"], f["text"]) for f in found}
    for page in (1, 2):
        for t in ("jane.doe@example.com", "+49 30 1234567", "DE89 3704 0044 0532 0130 00", "86 095 742 719"):
            assert (page, t) in texts, (page, t)
    assert not any("123456" == f["text"] for f in found)           # a plain number is not personal data
    assert len(found) == 8                                          # no extra hits nested inside the IBAN
    run("Redact.Mark", d, found)
    run("Redact.Apply", d)
    assert "jane.doe" not in d[0].get_text() and "ref 123456" in d[0].get_text()
    words = " ".join(w for ln in ocrmod.page_lines(d[1]) for _r, w, _c in ln.words)
    assert "jane" not in words and "DE89" not in words and "123456" in words


def test_auto_redact_arabic_digits():
    d = pymupdf.open()
    d.new_page()
    run("Text.Add", d, 1, (72, 100), "الهاتف ٠٣٠١٢٣٤٥٦٧ والبريد user@example.com")
    kinds = {f["kind"] for f in run("Redact.Find", d, kinds=list(PATTERNS))}
    assert kinds == {"Email address", "Phone number (DE)"}


@pytest.mark.parametrize("code", ["de", "ar"])
def test_translations_keep_placeholders(code):
    import re
    lang.set_language(code)
    try:
        for en, s in lang._table.items():
            assert sorted(re.findall(r"\{[^}]*\}", en)) == sorted(re.findall(r"\{[^}]*\}", s)), en
        assert lang.tr("Page {n}", n=3) != "Page 3"
    finally:
        lang.set_language("en")
