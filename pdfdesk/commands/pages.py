"""Page-range parsing shared by commands: '1-3,7,10-' -> zero-based indexes."""
import re

from ..lang import tr


def parse_range(spec: str | None, count: int) -> list[int]:
    """'1-3, 7, 10-', 'odd', 'even' or 'all'. Spaces, en dashes and semicolons are allowed, as people type them."""
    if not spec or spec.strip().lower() == "all":
        return list(range(count))
    out: list[int] = []
    for part in re.split(r"[,;]", spec.replace("–", "-").replace("—", "-")):
        part = part.replace(" ", "").lower()
        if not part:
            continue
        if part in ("odd", "even"):
            out += [i for i in range(count) if (i % 2 == 0) == (part == "odd")]
            continue
        m = re.fullmatch(r"(\d*)(-?)(\d*)", part)
        if not m or not (m.group(1) or m.group(3)):
            raise ValueError(tr("“{part}” is not a page range. Use page numbers like 1-3, 7 (this document has "
                                "{n} pages).", part=part, n=count))
        lo = int(m.group(1)) if m.group(1) else 1
        hi = (int(m.group(3)) if m.group(3) else count) if m.group(2) else lo
        if not (1 <= lo <= hi <= count):
            raise ValueError(tr("Pages {part} are not in this document, which has {n} pages.", part=part, n=count))
        out += range(lo - 1, hi)
    return out
