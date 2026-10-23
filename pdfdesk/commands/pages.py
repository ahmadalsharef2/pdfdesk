"""Page-range parsing shared by commands: '1-3,7,10-' -> zero-based indexes."""


def parse_range(spec: str | None, count: int) -> list[int]:
    if not spec or spec == "all":
        return list(range(count))
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if part in ("odd", "even"):
            out += [i for i in range(count) if (i % 2 == 0) == (part == "odd")]
            continue
        a, _, b = part.partition("-")
        lo = int(a) if a else 1
        hi = (int(b) if b else count) if "-" in part else lo
        if not (1 <= lo <= hi <= count):
            raise ValueError(f"page range {part!r} outside 1-{count}")
        out += range(lo - 1, hi)
    return out
