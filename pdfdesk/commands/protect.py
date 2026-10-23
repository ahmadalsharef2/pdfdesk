"""Protect commands (plan phase 3). Redaction removes content; tests verify raw streams."""
from __future__ import annotations

import re

import pymupdf

from .pages import parse_range
from .registry import command


@command("Redact.MarkRects")
def mark_rects(doc, page: int, rects, fill=(0, 0, 0), overlay: str | None = None, text_color=(1, 1, 1)):
    p = doc[page - 1]
    for r in rects:
        p.add_redact_annot(pymupdf.Rect(r), text=overlay, fill=fill, text_color=text_color,
                           fontsize=8, align=1, cross_out=False)


@command("Redact.MarkPages")
def mark_pages(doc, pages: str, fill=(0, 0, 0)):
    for i in parse_range(pages, doc.page_count):
        p = doc[i]
        p.add_redact_annot(p.rect, fill=fill, cross_out=False)


PATTERNS = {
    "Email address": r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+",
    "Phone number (US/CA)": r"(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}",
    "Phone number (international)": r"\+\d{1,3}(?:[ .-]?\d{2,4}){2,5}",
    "Credit card number": r"(?:\d[ -]?){12,18}\d",
    "US Social Security number": r"\d{3}-\d{2}-\d{4}",
    "Canada Social Insurance number": r"\d{3}[ -]\d{3}[ -]\d{3}",
    "IBAN": r"[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?",
    "Date": r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}-\d{2}-\d{2}",
}


def luhn_ok(s: str) -> bool:
    digits = [int(c) for c in s if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def sin_ok(s: str) -> bool:
    digits = [int(c) for c in s if c.isdigit()]
    return len(digits) == 9 and luhn_ok_any(digits)


def luhn_ok_any(digits: list[int]) -> bool:
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


CHECKS = {"Credit card number": luhn_ok, "Canada Social Insurance number": sin_ok}


@command("Redact.Search")
def search(doc, needle: str | None = None, pattern: str | None = None, whole_words=False,
           case_sensitive=False, overlay: str | None = None, fill=(0, 0, 0), pages: str | None = None,
           kind: str | None = None):
    """Mark text hits for redaction: exact string, regex, or a named pattern kind. Returns number of marks."""
    check = None
    if kind:
        pattern, check = PATTERNS[kind], CHECKS.get(kind)
    n = 0
    flags = 0 if case_sensitive else re.I
    for i in parse_range(pages, doc.page_count):
        p = doc[i]
        hits = []
        if needle is not None:
            q = pymupdf.TEXT_DEHYPHENATE
            for r in p.search_for(needle):
                hits.append(r)
            if not case_sensitive is False:
                pass
            if whole_words:
                words = p.get_text("words")
                pat = re.compile(rf"^{re.escape(needle)}$", flags)
                hits = [pymupdf.Rect(w[:4]) for w in words if pat.match(w[4].strip(".,;:()"))]
            if case_sensitive:
                txt = p.get_text()
                hits = [r for r in hits if needle in p.get_textbox(r + (-1, -1, 1, 1))]
        else:
            rx = re.compile(pattern, flags)
            for x0, y0, x1, y1, raw, *_ in p.get_text("words"):
                w = raw.strip(".,;:()<>")
                if w and rx.fullmatch(w) and (check is None or check(w)):
                    box = pymupdf.Rect(x0, y0, x1, y1)
                    exact = p.search_for(w, clip=box + (-1, -1, 1, 1)) if w != raw else []
                    hits.append(exact[0] if exact else box)
            # matches spanning several words (numbers with spaces, "(415) 555-0142") via line text
            for blk in p.get_text("dict")["blocks"]:
                for line in blk.get("lines", []):
                    t = "".join(s["text"] for s in line["spans"])
                    for m in rx.finditer(t):
                        if " " in m.group(0).strip() and (check is None or check(m.group(0))):
                            hits += p.search_for(m.group(0).strip())
        seen = set()
        for r in hits:
            key = tuple(round(v) for v in r)
            if key in seen:
                continue
            seen.add(key)
            p.add_redact_annot(r, text=overlay, fill=fill, fontsize=8, align=1, text_color=(1, 1, 1),
                               cross_out=False)
            n += 1
    return n


@command("Redact.Apply")
def apply(doc, images: int = 2, graphics: int = 1, text: int = 0):
    """Apply every Redact annotation, then drop revision history on save (caller uses garbage=4, clean)."""
    n = 0
    for p in doc:
        if any(a.type[0] == pymupdf.PDF_ANNOT_REDACT for a in p.annots() or []):
            p.apply_redactions(images=images, graphics=graphics, text=text)
            n += 1
    return n


@command("Redact.Whiteout")
def whiteout(doc, page: int, rects):
    p = doc[page - 1]
    for r in rects:
        p.add_redact_annot(pymupdf.Rect(r), fill=(1, 1, 1), cross_out=False)
    p.apply_redactions()


@command("Protect.RemoveHiddenInfo")
def remove_hidden(doc, annots=True, attachments=True, bookmarks=False, form_fields=True,
                  hidden_text=True, links_actions_js=True, metadata=True, **_ignored):
    doc.scrub(attached_files=attachments, clean_pages=True, embedded_files=attachments,
              hidden_text=hidden_text, javascript=links_actions_js, metadata=metadata,
              redactions=False, remove_links=links_actions_js, reset_fields=form_fields,
              reset_responses=annots, thumbnails=True, xml_metadata=metadata)
    if annots:
        for p in doc:
            for a in list(p.annots() or []):
                p.delete_annot(a)
    if not bookmarks:
        pass
    else:
        doc.set_toc([])


@command("Protect.Encrypt")
def encrypt_save(doc, out: str, user_pw: str = "", owner_pw: str = "owner", permissions: int | None = None,
                 aes256: bool = True):
    perm = permissions if permissions is not None else (
        pymupdf.PDF_PERM_ACCESSIBILITY | pymupdf.PDF_PERM_PRINT | pymupdf.PDF_PERM_COPY)
    doc.save(out, encryption=pymupdf.PDF_ENCRYPT_AES_256 if aes256 else pymupdf.PDF_ENCRYPT_AES_128,
             user_pw=user_pw, owner_pw=owner_pw, permissions=perm, garbage=3, deflate=True)

