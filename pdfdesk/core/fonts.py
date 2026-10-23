"""Find installed font files by family and style (fc-list; fc-match is unreliable on some setups)."""
from __future__ import annotations

import functools
import re
import subprocess

FALLBACK = {
    "sans": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "serif": "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
}


@functools.lru_cache(maxsize=1)
def _catalog() -> list[tuple[str, str, str]]:
    try:
        out = subprocess.run(["fc-list", "--format", "%{family}|%{style}|%{file}\n"],
                             capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    rows = []
    for line in out.splitlines():
        fam, _, rest = line.partition("|")
        style, _, path = rest.partition("|")
        if path.lower().endswith((".ttf", ".otf")):
            rows.append((fam.split(",")[0].strip(), style.split(",")[0].strip(), path))
    return rows


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
    return find("DejaVu Sans") or FALLBACK["sans"]
