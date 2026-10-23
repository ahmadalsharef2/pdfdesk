import pymupdf

from pdfdesk.commands import compare as cmp
from pdfdesk.commands import ocr as ocrmod
from pdfdesk.commands import run

import build  # noqa: E402


def test_compare_finds_known_edits(tmp_path):
    build.contract(tmp_path / "a.pdf", False)
    build.contract(tmp_path / "b.pdf", True)
    old, new = pymupdf.open(tmp_path / "a.pdf"), pymupdf.open(tmp_path / "b.pdf")
    res, changes = run("Compare.Run", old, new)
    kinds = sorted((c.kind, c.new_page if c.new_page is not None else c.old_page) for c in changes)
    assert kinds == [("insert", 2), ("replace", 1)]          # p.3 insertion, p.2 replacement (0-based pages)
    assert cmp.summary(changes)["replace"] == 1 and cmp.summary(changes)["insert"] == 1
    assert res.page_count == 1 + 6
    p2 = res[2]
    assert "Replace: 1" in res[0].get_text() and len(list(p2.annots())) >= 2


def test_compare_identical_has_no_changes(tmp_path):
    build.contract(tmp_path / "a.pdf", False)
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
