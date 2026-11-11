"""The bridge the browser and phone apps call (pdfdesk/webapi.py), through its one entry point."""
import hashlib
import json
import os

import pymupdf
from conftest import make_contract

from pdfdesk import webapi
from pdfdesk.core import license

KEY = "TEST-KEY-12345"                                  # stands in for the product key, which is not in this repository
license.KEY_SHA256 = hashlib.sha256(b"TESTKEY12345").hexdigest()
webapi.activate(KEY)


def call(fn, **args):
    res, blob = webapi.call(fn, json.dumps(args))
    res = json.loads(res)
    assert "error" not in res, res
    return (res["ok"], blob) if blob is not None else res["ok"]


def test_nothing_runs_before_the_product_key():
    webapi._unlocked = False
    assert "error" in json.loads(webapi.call("blank", "{}")[0])
    assert call("activate", key="wrong") is False
    assert call("activate", key=KEY.lower().replace("-", " ")) is True
    assert call("available")


def test_open_render_edit_undo_save(v1_path):
    doc = call("open_file", path=v1_path, name="v1.pdf")
    sid = doc["id"]
    assert len(doc["pages"]) == 6 and not doc["modified"]
    meta, pixels = call("render", sid=sid, page=0, scale=0.5)
    assert len(pixels) == meta["width"] * meta["height"] * 4 and pixels[3] == 255
    words = call("words", sid=sid, page=0)
    a, b = words[0], words[2]
    call("run", sid=sid, name="Comment.Highlight", args={"page": 1, "start": a[:2], "stop": b[2:4]}, label="Highlight")
    call("run", sid=sid, name="Pages.Rotate", args={"angle": 90, "pages": "2"})
    info = call("info", sid=sid)
    assert info["modified"] and info["pages"][1][2] == 90 and info["undo"] == "Pages.Rotate"
    assert [c["kind"] for c in call("page_items", sid=sid, page=0)["comments"]] == ["Highlight"]
    assert call("undo", sid=sid) == "Pages.Rotate" and call("info", sid=sid)["pages"][1][2] == 0
    assert call("find", sid=sid, text="net 30")[0][0] == 0
    meta, data = call("save", sid=sid)
    saved = pymupdf.open("pdf", data)
    assert saved.page_count == 6 and len(list(saved[0].annots())) == 1 and not call("info", sid=sid)["modified"]
    call("close", sid=sid)


def test_errors_passwords_and_exports(v1_path, tmp_path):
    res = json.loads(webapi.call("run", json.dumps({"sid": 99, "name": "Pages.Reverse"}))[0])
    assert res["kind"] == "KeyError"
    sid = call("open_file", path=v1_path, name="v1.pdf")["id"]
    call("protect", sid=sid, user_pw="open", owner_pw="own")
    _meta, data = call("save", sid=sid)
    locked = tmp_path / "locked.pdf"
    locked.write_bytes(data)
    res = json.loads(webapi.call("open_file", json.dumps({"path": str(locked), "name": "locked.pdf"}))[0])
    assert res["kind"] == "NeedsPassword"
    again = call("open_file", path=str(locked), name="locked.pdf", password="open")
    assert again["protected"] and again["readonly"]              # opened with the user password only
    meta, data = call("export", sid=sid, kind="png", pages="1-2", dpi=40)
    assert meta["name"] == "v1.zip" and data[:2] == b"PK"
    meta, data = call("export", sid=sid, kind="extract", pages="2")
    assert pymupdf.open("pdf", data).page_count == 1
    img, other = tmp_path / "scan.png", tmp_path / "other.pdf"      # v1_path itself is the protected save now
    make_contract(other)
    pymupdf.open(other)[0].get_pixmap(dpi=40).save(img)
    made = call("create", paths=[str(img), str(other)])
    assert len(made["pages"]) == 7 and made["modified"]
    assert "Comment.Highlight" in call("available") and os.path.isdir(webapi.WORK)
