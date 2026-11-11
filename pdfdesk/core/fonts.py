"""Find installed font files by family and style (fc-list; fc-match is unreliable on some setups).

Where there is no fc-list (macOS, Windows, the browser and phone builds) the system font folders are read
instead, and the fonts in pdfdesk/fonts/ are always there, so text never depends on what is installed."""
from __future__ import annotations

import functools
import os
import re
import struct
import subprocess

_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts")
BUNDLED = [("DejaVu Sans", "Book", os.path.join(_DIR, "DejaVuSans.ttf")),
           ("DejaVu Sans", "Bold", os.path.join(_DIR, "DejaVuSans-Bold.ttf")),
           ("DejaVu Sans Mono", "Book", os.path.join(_DIR, "DejaVuSansMono.ttf")),
           ("Great Vibes", "Regular", os.path.join(_DIR, "GreatVibes-Regular.ttf"))]
SYSTEM_DIRS = ["/System/Library/Fonts", "/System/Library/Fonts/Supplemental", "/Library/Fonts", "~/Library/Fonts",
               os.path.join(os.environ.get("WINDIR", ""), "Fonts"),
               os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts")]


def _names(path: str) -> tuple[str, str] | None:
    """(family, style) from a font file's name table."""
    try:
        with open(path, "rb") as f:
            for _ in range(struct.unpack(">4xH6x", f.read(12))[0]):
                tag, _sum, offset, length = struct.unpack(">4sLLL", f.read(16))
                if tag == b"name":
                    f.seek(offset)
                    data = f.read(length)
                    break
            else:
                return None
        _fmt, n, strings = struct.unpack(">HHH", data[:6])
        got: dict[int, str] = {}
        for k in range(n):
            platform, _enc, _lang, name_id, length, offset = struct.unpack(">6H", data[6 + 12 * k:18 + 12 * k])
            if name_id in (1, 2) and (name_id not in got or platform == 3):
                raw = data[strings + offset:strings + offset + length]
                got[name_id] = raw.decode("utf-16-be" if platform in (0, 3) else "mac-roman", "replace")
    except (OSError, struct.error):
        return None
    return (got[1], got.get(2, "Regular")) if 1 in got else None


def _scan(folders) -> list[tuple[str, str, str]]:
    rows = []
    for folder in folders:
        folder = os.path.expanduser(folder)
        if not folder or not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            if name.lower().endswith((".ttf", ".otf")):
                names = _names(os.path.join(folder, name))
                if names:
                    rows.append((*names, os.path.join(folder, name)))
    return rows


@functools.lru_cache(maxsize=1)
def _catalog() -> list[tuple[str, str, str]]:
    try:
        out = subprocess.run(["fc-list", "--format", "%{family}|%{style}|%{file}\n"],
                             capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        out = ""
    rows = []
    for line in out.splitlines():
        fam, _, rest = line.partition("|")
        style, _, path = rest.partition("|")
        if path.lower().endswith((".ttf", ".otf")):
            rows.append((fam.split(",")[0].strip(), style.split(",")[0].strip(), path))
    return (rows or _scan(SYSTEM_DIRS)) + BUNDLED


def find(family: str, bold: bool = False, italic: bool = False) -> str | None:
    """Return a font file for family, preferring the requested style; None if family not installed."""
    want = family.lower().replace(" ", "")
    cands = [r for r in _catalog() if r[0].lower().replace(" ", "") == want]
    if not cands:
        return None

    def score(r):
        s = r[1].lower()
        sc = 0
        sc += 4 if (("bold" in s) == bold) else 0
        sc += 4 if ((("italic" in s) or ("oblique" in s)) == italic) else 0
        sc += 2 if s in ("regular", "book", "normal", "roman") and not bold and not italic else 0
        sc -= 3 if any(w in s for w in ("thin", "light", "semi", "extra", "black", "condensed", "medium")) else 0
        return sc
    return max(cands, key=score)[2]


def for_pdf_font(pdf_font_name: str) -> tuple[str | None, str]:
    """Map a PDF font name like 'ABCDEF+Calibri-BoldItalic' to (file or None, base14 fallback)."""
    name = pdf_font_name.split("+", 1)[-1]
    low = name.lower()
    bold = "bold" in low or "black" in low or "heavy" in low
    italic = "italic" in low or "oblique" in low
    family = re.split(r"[-,]", name)[0]
    family = re.sub(r"(PSMT|PS|MT|Std|Pro)$", "", family)
    family = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", family)  # TimesNewRoman -> Times New Roman
    aliases = {"arial": "Liberation Sans", "helvetica": "Liberation Sans", "times new roman": "Liberation Serif",
               "times": "Liberation Serif", "courier new": "Liberation Mono", "courier": "Liberation Mono",
               "calibri": "Carlito", "cambria": "Caladea"}
    path = find(family, bold, italic) or find(aliases.get(family.lower(), ""), bold, italic)
    serif = any(w in low for w in ("times", "serif", "roman", "georgia", "cambria", "garamond"))
    mono = "courier" in low or "mono" in low
    base = ("cour" if mono else "tiro" if serif else "helv")
    if base == "helv":
        base = {(True, True): "hebi", (True, False): "hebo", (False, True): "heit"}.get((bold, italic), "helv")
    elif base == "tiro":
        base = {(True, True): "tibi", (True, False): "tibo", (False, True): "tiit"}.get((bold, italic), "tiro")
    return path, base


def script_font() -> str | None:
    """A handwriting-style font for typed signatures."""
    for fam in ("Segoe Script", "Z003", "Dancing Script", "Great Vibes", "URW Chancery L"):
        p = find(fam) or find(fam, italic=True)
        if p:
            return p
    return None


def unicode_font() -> str:
    return find("DejaVu Sans") or BUNDLED[0][2]
