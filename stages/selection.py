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


MIN_VOL, MIN_SCHOOLS, MAX_SCHOOLS = 100, 8, 12


def _vol(text):
    return int(str(text).replace(",", "").strip())


def suggest_schools(schools):
    """Apply the volume rule to one blog's list. Returns (1-based numbers in pick order, top-up numbers).

    Every school with volume >= 100, highest first, at most 12; if fewer than 8, top up with the
    next highest. Ties go to the higher competitor count. Raises ValueError if a volume is blank.
    """
    missing = [s["name"] for s in schools if not str(s["volume"]).strip()]
    if missing:
        raise ValueError("no volume yet for: " + ", ".join(missing))
    ranked = sorted(range(1, len(schools) + 1),
                    key=lambda n: (-_vol(schools[n - 1]["volume"]), -int(schools[n - 1]["count"] or 0), n))
    chosen = [n for n in ranked if _vol(schools[n - 1]["volume"]) >= MIN_VOL][:MAX_SCHOOLS]
    topup = [n for n in ranked if n not in chosen][:max(0, MIN_SCHOOLS - len(chosen))]
    return chosen + topup, set(topup)


def parse_vols(text, n):
    """'1:320, 2:90, 5: 1,500' -> {1: 320, 2: 90, 5: 1500} for a list of n schools."""
    found = re.findall(r"(\d+)\s*[:=]\s*(\d{1,3}(?:,\d{3})+|\d+)", text)
    if not found:
        raise ValueError("no 'number: volume' pairs found")
    out = {}
    for num, vol in found:
        num = int(num)
        if not 1 <= num <= n:
            raise ValueError(f"school {num} is outside 1-{n}")
        out[num] = _vol(vol)
    return out
