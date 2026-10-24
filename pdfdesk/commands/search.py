"""Text search that also matches Arabic presentation forms and ligatures (NFKC-normalised)."""
from __future__ import annotations

import unicodedata

import pymupdf

from .registry import command


def norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s).replace(" ", " ").casefold()


def find(page: pymupdf.Page, text: str) -> list[pymupdf.Rect]:
    if not text.strip():
        return []
    hits = page.search_for(text)
    if hits:
        return hits
    # fallback: match normalised word sequences (handles presentation forms in RTL text)
    target = norm(text).split()
    words = page.get_text("words", sort=True)
    nw = [norm(w[4]) for w in words]
    out = []
    k = len(target)
    # right-to-left lines come out in visual order, so also try the words reversed
    for tgt in ([target, target[::-1]] if k > 1 else [target]):
        for i in range(len(nw) - k + 1):
            seq = nw[i:i + k]
            if k == 1:
                ok = tgt[0] in seq[0]
            else:
                ok = (all(a == b for a, b in zip(seq[1:-1], tgt[1:-1]))
                      and seq[0].endswith(tgt[0]) and seq[-1].startswith(tgt[-1]))
            if ok:
                r = pymupdf.Rect()
                for w in words[i:i + k]:
                    r |= pymupdf.Rect(w[:4])
                if r not in out:
                    out.append(r)
    return out


@command("Search.Folder")
def folder(root: str, text: str, recursive: bool = True, whole_word: bool = False,
           case: bool = False, limit: int = 2000) -> list[dict]:
    """Search every PDF under a folder (Foxit's Advanced Search > All PDF documents in…).
    Returns {path, page, context} per hit; files that fail to open are reported with an error."""
    import os
    import re
    flags = 0 if case else re.IGNORECASE
    pat = re.compile((r"\b%s\b" if whole_word else "%s") % re.escape(text), flags)
    out = []
    walk = os.walk(root) if recursive else [(root, [], os.listdir(root))]
    for d, _, files in walk:
        for f in sorted(files):
            if not f.lower().endswith(".pdf"):
                continue
            p = os.path.join(d, f)
            try:
                doc = pymupdf.open(p)
                if doc.needs_pass:
                    out.append({"path": p, "page": None, "context": "(password protected, skipped)"})
                    continue
                for page in doc:
                    t = page.get_text()
                    for m in pat.finditer(t):
                        a, b = max(0, m.start() - 40), min(len(t), m.end() + 40)
                        out.append({"path": p, "page": page.number + 1,
                                    "context": t[a:b].replace("\n", " ").strip()})
                        if len(out) >= limit:
                            return out
            except Exception as e:  # noqa: BLE001
                out.append({"path": p, "page": None, "context": f"(could not read: {e})"})
    return out
