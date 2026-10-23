import re

import pymupdf

from pdfdesk.commands import run


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
