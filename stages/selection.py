"""Chat helpers: reading a school selection like "1-12 drop 4,7", deduping new keywords."""

import re


def _numbers(text, n):
    out = set()
    for part in re.split(r"[,\s]+", text.strip()):
        if not part:
            continue
        if part.lower() == "all":
            out.update(range(1, n + 1))
            continue
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if not m:
            raise ValueError(f"can't read '{part}'")
        lo, hi = int(m.group(1)), int(m.group(2) or m.group(1))
        if lo > hi or lo < 1 or hi > n:
            raise ValueError(f"'{part}' is outside 1-{n}")
        out.update(range(lo, hi + 1))
    return out


def parse_selection(text, n):
    """'1-12 drop 4,7' -> sorted 1-based numbers out of a list of n schools."""
    keep, _, drop = text.lower().partition("drop")
    chosen = _numbers(keep, n) - _numbers(drop, n)
    if not chosen:
        raise ValueError("no schools selected")
    return sorted(chosen)


def new_keywords(existing, keywords):
    """(fresh, skipped): keywords not already in the sheet or earlier in this batch."""
    seen = {k.strip().lower() for k in existing}
    fresh, skipped = [], []
    for k in keywords:
        k = k.strip()
        if not k:
            continue
        if k.lower() in seen:
            skipped.append(k)
        else:
            seen.add(k.lower())
            fresh.append(k)
    return fresh, skipped
