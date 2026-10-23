import pymupdf

from pdfdesk.commands import run


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
