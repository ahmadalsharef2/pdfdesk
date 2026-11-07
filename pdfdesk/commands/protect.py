"""Redaction, hidden-information removal and encryption. Redaction removes content for good."""
from __future__ import annotations

import re
from collections import Counter

import pymupdf

from . import ocr
from .pages import parse_range
from .registry import command

# Arabic-Indic and Persian digits map to ASCII before matching; one character each, so offsets stay valid.
DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")

RTL = re.compile("[\u0590-\u08ff\ufb1d-\ufdff\ufe70-\ufeff]")
RTL_DIGIT_RUN = re.compile(r"\d+")

PATTERNS = {
    "Email address": r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+",
    "Phone number (DE)": r"(?:\+49[ .-]?(?:\(0\))?|0)\d{2,5}[ /.-]?\d{3,8}(?:[ .-]?\d{1,6})?",
    "Phone number (US/CA)": r"(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}",
    "Phone number (international)": r"\+\d{1,3}(?:[ .-]?\d{2,4}){2,5}",
    "Credit card number": r"(?:\d[ -]?){12,18}\d",
    "IBAN": r"[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?",
    "US Social Security number": r"\d{3}-\d{2}-\d{4}",
    "Canada Social Insurance number": r"\d{3}[ -]\d{3}[ -]\d{3}",
    "German tax ID (Steuer-ID)": r"\d{2} ?\d{3} ?\d{3} ?\d{3}",
    "Date": r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}-\d{2}-\d{2}",
}


def luhn_ok(s: str) -> bool:
    digits = [int(c) for c in s if c.isdigit()]
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return bool(digits) and total % 10 == 0


def card_ok(s: str) -> bool:
    return 13 <= sum(c.isdigit() for c in s) <= 19 and luhn_ok(s)


def sin_ok(s: str) -> bool:
    return sum(c.isdigit() for c in s) == 9 and luhn_ok(s)


def iban_ok(s: str) -> bool:
    t = s.replace(" ", "").upper()
    if not 15 <= len(t) <= 34:
        return False
    digits = "".join(str(int(c, 36)) for c in t[4:] + t[:4])
    return int(digits) % 97 == 1


def steuer_id_ok(s: str) -> bool:
    """German tax ID: 11 digits, one digit repeated in the first ten, ISO 7064 MOD 11,10 check digit."""
    d = [int(c) for c in s if c.isdigit()]
    if len(d) != 11 or d[0] == 0 or len(Counter(d[:10])) not in (8, 9):
        return False
    prod = 10
    for x in d[:10]:
        total = (x + prod) % 10 or 10
        prod = total * 2 % 11
    return (11 - prod) % 10 == d[10]


CHECKS = {"Credit card number": card_ok, "Canada Social Insurance number": sin_ok, "IBAN": iban_ok,
          "German tax ID (Steuer-ID)": steuer_id_ok}


def _regex(pattern: str, whole_words: bool, case_sensitive: bool) -> re.Pattern:
    if whole_words:
        pattern = rf"(?<!\w)(?:{pattern})(?!\w)"
    return re.compile(pattern, 0 if case_sensitive else re.I)


def _page_lines(page: pymupdf.Page, ocr_lines=None) -> list[list[tuple[pymupdf.Rect, str]]]:
    """Words grouped by line, [[(rect, word), ...], ...], from the text layer or from OCR."""
    if ocr_lines is not None:
        return [[(r, t) for r, t, _conf in ln.words] for ln in ocr_lines]
    # MuPDF starts a new line at every change of writing direction, so join words of a block by height
    lines: list[tuple[int, pymupdf.Rect, list]] = []
    for x0, y0, x1, y1, w, block, *_ in page.get_text("words"):
        r = pymupdf.Rect(x0, y0, x1, y1)
        ln = next((ln for ln in lines if ln[0] == block and min(ln[1].y1, r.y1) - max(ln[1].y0, r.y0) > r.height / 2), None)
        if ln is None:
            lines.append((block, pymupdf.Rect(r), [(r, w)]))
        else:
            ln[1].include_rect(r)
            ln[2].append((r, w))
    return [sorted(words, key=lambda rw: rw[0].x0) for _b, _r, words in lines]


def _logical(text: str) -> str:
    """ASCII digits; in a right-to-left line the text layer holds digit runs in visual order, so turn them
    back. Lengths do not change, so match offsets still point into the original text."""
    t = text.translate(DIGITS)
    return RTL_DIGIT_RUN.sub(lambda m: m.group(0)[::-1], t) if RTL.search(t) else t


def _find_in_lines(page, lines, rx, check=None, exact=True):
    """(rect, text) for every match of rx in the lines' text; a match may span several words."""
    out = []
    for words in lines:
        text, spans = "", []
        for r, w in words:
            if text:
                text += " "
            spans.append((len(text), len(text) + len(w), r))
            text += w
        for m in rx.finditer(_logical(text)):
            hit = text[m.start():m.end()]
            if check and not check(hit):
                continue
            box = pymupdf.Rect()
            for a, b, r in spans:
                if a < m.end() and b > m.start():
                    box |= r
            if exact:                       # the text layer gives glyph-exact boxes; OCR boxes are already tight
                tight = page.search_for(hit, clip=box + (-1, -1, 1, 1))
                if tight:
                    box = pymupdf.Rect()
                    for r in tight:
                        box |= r
            out.append((box, hit))
    return out


@command("Redact.Find")
def find(doc, kinds=None, needle: str | None = None, pattern: str | None = None, whole_words=False,
         case_sensitive=False, pages: str | None = None, ocr_scans: bool = False, languages=("en",),
         dpi: int = 300, progress=None) -> list[dict]:
    """Find what to redact, without marking anything. `kinds` are PATTERNS names; a needle is a plain string,
    a pattern a regex. Scanned pages (no text layer) are read with PaddleOCR when ocr_scans is on, so the
    hits can be blacked out of the image. Returns [{page, rect, kind, text, scanned}]."""
    searches = []
    if needle is not None:
        searches.append((needle, _regex(re.escape(needle), whole_words, case_sensitive), None))
    if pattern is not None:
        searches.append((pattern, _regex(pattern, whole_words, case_sensitive), None))
    for k in kinds or ():
        searches.append((k, _regex(PATTERNS[k], True, True), CHECKS.get(k)))
    out = []
    idx = parse_range(pages, doc.page_count)
    for n, i in enumerate(idx):
        if progress:
            progress(n, len(idx))
        page = doc[i]
        scanned = ocr_scans and not page.get_text().strip()
        lines = _page_lines(page, ocr.page_lines(page, languages, dpi, every_script=True) if scanned else None)
        hits = [{"page": i + 1, "rect": rect, "kind": kind, "text": text, "scanned": scanned}
                for kind, rx, check in searches
                for rect, text in _find_in_lines(page, lines, rx, check, exact=not scanned) if not rect.is_empty]
        out += _outermost(hits)
    return out


def _outermost(hits: list[dict]) -> list[dict]:
    """Drop hits inside a longer one (a phone-like digit run inside an IBAN), keeping the first of equals."""
    hits = sorted(hits, key=lambda h: -len(h["text"]))
    keep = []
    for h in hits:
        if not any((k["rect"] + (-1, -1, 1, 1)).contains(h["rect"]) for k in keep):
            keep.append(h)
    return sorted(keep, key=lambda h: (h["rect"].y0, h["rect"].x0))


@command("Redact.Mark")
def mark(doc, items: list[dict], overlay: str | None = None, fill=(0, 0, 0)) -> int:
    for it in items:
        doc[it["page"] - 1].add_redact_annot(pymupdf.Rect(it["rect"]), text=overlay, fill=fill, fontsize=8,
                                             align=1, text_color=(1, 1, 1), cross_out=False)
    return len(items)


@command("Redact.Search")
def search(doc, needle: str | None = None, pattern: str | None = None, kind: str | None = None,
           whole_words=False, case_sensitive=False, overlay: str | None = None, fill=(0, 0, 0),
           pages: str | None = None, ocr_scans: bool = False, languages=("en",)) -> int:
    """Find and mark in one step. Returns the number of marks."""
    items = find(doc, kinds=[kind] if kind else None, needle=needle, pattern=pattern, whole_words=whole_words,
                 case_sensitive=case_sensitive, pages=pages, ocr_scans=ocr_scans, languages=languages)
    return mark(doc, items, overlay, fill)


@command("Redact.MarkRects")
def mark_rects(doc, page: int, rects, fill=(0, 0, 0), overlay: str | None = None):
    mark(doc, [{"page": page, "rect": r} for r in rects], overlay, fill)


@command("Redact.MarkPages")
def mark_pages(doc, pages: str, fill=(0, 0, 0)):
    for i in parse_range(pages, doc.page_count):
        doc[i].add_redact_annot(doc[i].rect, fill=fill, cross_out=False)


@command("Redact.Apply")
def apply(doc, images: int = pymupdf.PDF_REDACT_IMAGE_PIXELS, graphics: int = 1, text: int = 0) -> int:
    """Apply every redaction mark. Image pixels under a mark are blanked, so scans are redacted too.
    The caller saves with garbage=4 and clean=True to drop the old revisions."""
    n = 0
    for p in doc:
        if any(True for _ in p.annots(types=[pymupdf.PDF_ANNOT_REDACT])):
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
                  hidden_text=True, links_actions_js=True, metadata=True):
    doc.scrub(attached_files=attachments, clean_pages=True, embedded_files=attachments,
              hidden_text=hidden_text, javascript=links_actions_js, metadata=metadata,
              redactions=False, remove_links=links_actions_js, reset_fields=form_fields,
              reset_responses=annots, thumbnails=True, xml_metadata=metadata)
    if annots:
        for p in doc:
            for a in list(p.annots()):
                p.delete_annot(a)
    if bookmarks:
        doc.set_toc([])


@command("Protect.Encrypt")
def encrypt_save(doc, out: str, user_pw: str = "", owner_pw: str = "owner", permissions: int | None = None,
                 aes256: bool = True):
    perm = permissions if permissions is not None else (
        pymupdf.PDF_PERM_ACCESSIBILITY | pymupdf.PDF_PERM_PRINT | pymupdf.PDF_PERM_COPY)
    doc.save(out, encryption=pymupdf.PDF_ENCRYPT_AES_256 if aes256 else pymupdf.PDF_ENCRYPT_AES_128,
             user_pw=user_pw, owner_pw=owner_pw, permissions=perm, garbage=3, deflate=True)
