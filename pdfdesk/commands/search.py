"""Text search that also matches Arabic presentation forms and ligatures (NFKC-normalised)."""
from __future__ import annotations

import unicodedata

import pymupdf


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
