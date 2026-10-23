import pymupdf
import pytest

from pdfdesk.core import security as sec


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
