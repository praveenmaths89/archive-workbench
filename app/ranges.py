"""Page-range parsing: '1-5, 8, 12-' -> [1,2,3,4,5,8,12,...total]."""
from __future__ import annotations

import re


def parse_pages(spec: str | list[int] | None, total: int) -> list[int] | None:
    """Return sorted 1-based page numbers, or None for 'all pages'.

    Accepts '1-3,5', '5-' (to the end), '-3' (first three), 'all'/'' (everything), or a list of ints.
    Raises ValueError with a message fit to show the user.
    """
    if spec is None:
        return None
    if isinstance(spec, list):
        nums = sorted({int(n) for n in spec})
        bad = [n for n in nums if not 1 <= n <= total]
        if bad:
            raise ValueError(f"page {bad[0]} is outside 1-{total}")
        return nums or None
    s = str(spec).strip().lower()
    if s in ("", "all", "*"):
        return None
    out: set[int] = set()
    for part in re.split(r"[,\s;]+", s):
        if not part:
            continue
        m = re.fullmatch(r"(\d*)\s*[-–]\s*(\d*)", part)
        if m and (m.group(1) or m.group(2)):
            a = int(m.group(1)) if m.group(1) else 1
            b = int(m.group(2)) if m.group(2) else total
            if a > b:
                raise ValueError(f"range '{part}' is backwards")
            if a < 1 or a > total:
                raise ValueError(f"page {a} is outside 1-{total}")
            out.update(range(a, min(b, total) + 1))  # an end past the last page is clamped
        elif part.isdigit():
            n = int(part)
            if not 1 <= n <= total:
                raise ValueError(f"page {n} is outside 1-{total}")
            out.add(n)
        else:
            raise ValueError(f"can't read '{part}' - use e.g. 1-5, 8, 12-")
    return sorted(out)
