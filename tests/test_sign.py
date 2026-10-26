import pymupdf

from pdfdesk.commands import run


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
