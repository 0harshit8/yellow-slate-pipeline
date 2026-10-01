"""School name rules. Pure functions, no I/O, so they're easy to test.

CMS naming rule (agreed with Yellow Slate, Oct 2026):
  - default: school name + area, e.g. "Delhi Public School Kalkaji"
  - board only when the same school has 2 campuses in one area (done by hand)
  - full names, no short forms (DPS -> Delhi Public School)
"""

import re
from difflib import SequenceMatcher

# Short forms competitors use. Expanded before matching and before naming.
ALIASES = {
    "dps": "delhi public school",
    "kv": "kendriya vidyalaya",
    "dav": "dav public school",
    "gd goenka": "gd goenka public school",
    "ryan": "ryan international school",
    "bvb": "bharatiya vidya bhavan",
}

MERGE_THRESHOLD = 0.85


def normalize(name):
    """Lowercase, strip punctuation and filler, expand short forms."""
    n = name.lower().replace("&", " and ")
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    for short, full in ALIASES.items():
        if n.startswith(full):
            break
        if n == short or n.startswith(short + " "):
            n = full + n[len(short):]
            break
    n = re.sub(r"\b(sr|senior)\s+sec(ondary)?\b", "senior secondary", n)
    return n


GENERIC = {"the", "school", "schools", "public", "senior", "secondary", "sr", "sec", "high", "co", "ed"}


def core(name, places=()):
    """Normalized name without generic words or place names: 'Deepalaya School Kalkaji' -> 'deepalaya'."""
    drop = set(GENERIC)
    for p in places:
        drop.update(normalize(p).split())
    words = [w for w in normalize(name).split() if w not in drop]
    return " ".join(words) or normalize(name)


def similar(a, b, places=()):
    """Compare only the distinctive part of two names.

    Shared filler like 'Public School Kalkaji' must not count: on full names
    'DAV Public School Kalkaji' vs 'Kalka Public School Kalkaji' scores ~0.88.
    """
    ca, cb = core(a, places), core(b, places)
    if ca == cb:
        return 1.0
    return SequenceMatcher(None, ca, cb).ratio()


def merge(names_per_page):
    """names_per_page: {url: [school names]}.

    Returns [{"name", "count", "sources"}], sorted by how many pages list the school.
    A school counts once per page. Display name is the longest variant seen.
    """
    groups = []  # each: {"key", "variants": set, "sources": set}
    for url, names in names_per_page.items():
        for raw in names:
            raw = raw.strip()
            if not raw:
                continue
            key = normalize(raw)
            for g in groups:
                if key == g["key"] or similar(key, g["key"]) >= MERGE_THRESHOLD:
                    g["variants"].add(raw)
                    g["sources"].add(url)
                    break
            else:
                groups.append({"key": key, "variants": {raw}, "sources": {url}})

    out = [
        {"name": display_name(g["variants"]), "count": len(g["sources"]), "sources": sorted(g["sources"])}
        for g in groups
    ]
    out.sort(key=lambda s: (-s["count"], s["name"]))
    return out


def display_name(variants):
    """Longest variant that isn't ALL CAPS. If every variant shouts, title-case the longest."""
    normal = [v for v in variants if not v.isupper()]
    if normal:
        return max(normal, key=len)
    return max(variants, key=len).title()


def expand_short_form(name):
    """'DPS Kalkaji' -> 'Delhi Public School Kalkaji'. Keeps the original casing otherwise."""
    words = name.split()
    for short, full in ALIASES.items():
        if name.lower().startswith(full):
            return name
        n = len(short.split())
        if [w.lower().strip(".") for w in words[:n]] == short.split():
            return " ".join([full.title()] + words[n:])
    return name


def cms_name(school, area):
    """School name + area, unless the area is already in the name."""
    name = expand_short_form(re.sub(r"\s+", " ", school).strip())
    if area and area.lower() not in name.lower():
        name = f"{name} {area}"
    return name


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def blog_slug(keyword, city):
    """Yellow Slate blog URL pattern: best-schools-in-<area>-<city>.

    'schools in Hauz Khas' + 'Delhi' -> 'best-schools-in-hauz-khas-delhi'
    """
    slug = slugify(keyword)
    if not slug.startswith("best-"):
        slug = "best-" + slug
    city_slug = slugify(city)
    if city_slug and not slug.endswith("-" + city_slug):
        slug = f"{slug}-{city_slug}"
    return slug


def semrush_term(name, area="", city=""):
    """Bare school name for a Semrush lookup: no area, no city, no ', GK-II' style suffix.

    'K.R. Mangalam World School, GK-II' -> 'k r mangalam world school'
    'Dbra Cm Shri School Kalkaji' (area Kalkaji) -> 'dbra cm shri school'
    """
    n = re.sub(r",.*$", "", name)
    for place in (area, city):
        if place:
            n = re.sub(rf"\b{re.escape(place)}\b", " ", n, flags=re.I)
    n = re.sub(r"[^a-z0-9 ]", " ", n.lower())
    return " ".join(n.split()[:10])[:80].strip()


def school_email(name):
    """schoolname+area@gmail.com, letters and digits only. Pass the cms_name()."""
    return re.sub(r"[^a-z0-9]", "", name.lower()) + "@gmail.com"
