"""School name rules. Pure functions, no I/O, so they're easy to test.

CMS naming rule, rewritten Oct 10, 2026 against their live API and their real data.

  - default: the plain school name, NO area, e.g. "Delhi Public School"
  - board only when the same school has 2 campuses in one area (done by hand)
  - full names, no short forms (DPS -> Delhi Public School)

Why the area came off. The old rule appended it, which was a reasonable guess while they had
no convention of their own. Their API now settles it two ways:

  1. Their existing rows are plain names. Of 23 schools matched in the Oct 10 dry run, 22 are
     the bare name: "Kidzee" at delhi/kidzee-kalkaji, "Delhi Public School" at
     delhi/delhi-public-school-dwarka, "Kalka Public School", "Global Academy".
  2. POST /schools appends the area to the slug itself. Their own docs show it: name
     "Example School Kalkaji" with area "Kalkaji" returns delhi/example-school-kalkaji-kalkaji.
     So appending the area here doubles it in the URL.

Searching is unaffected either way, because their matching ignores an area inside the name.
This only matters on create, which is why it had to change before the first real batch.

Confirmation was asked for in message 3 to their tech team. If they come back wanting the area
in the name, cms_name() and the email are the only places to change.
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


def merge(names_per_page, city=""):
    """names_per_page: {url: [school]}, where a school is a name or {"name", "area"}.

    Returns [{"name", "area", "count", "sources"}], sorted by how many pages list the school.
    A school counts once per page. Display name is the longest variant seen.

    The area is the locality the pages put the school in. Pages that state different
    localities are describing different schools, so a group only ever holds one locality,
    plus any entries that named none. Empty stays empty rather than being guessed:
    stages/area.py decides what to do with a school whose locality is unknown.
    """
    seen = [(url, *_name_and_area(entry), _reviews(entry))
            for url, entries in names_per_page.items() for entry in entries]
    seen = [(url, raw, area, reviews) for url, raw, area, reviews in seen if raw]

    # Pages write the same school as "La Martiniere College, Hazratganj" and
    # "La Martiniere College, Lucknow". Those are one school, and the locality in the name is
    # what stops them matching, so every locality any page mentioned is discounted from the
    # comparison. Two campuses in different localities still differ by their own names.
    places = {area for _, _, area, _ in seen if area}
    if city:
        places.add(city)

    groups = []  # each: {"key", "variants": set, "sources": set, "area": str, "reviews": int}
    for url, raw, area, reviews in seen:
        key = normalize(raw)
        for g in groups:
            if not _same_place(area, g["area"]):
                continue
            if key == g["key"] or similar(key, g["key"], places) >= MERGE_THRESHOLD:
                break
        else:
            g = {"key": key, "variants": set(), "sources": set(), "area": "", "reviews": 0}
            groups.append(g)
        g["variants"].add(raw)
        g["sources"].add(url)
        if area and not g["area"]:
            g["area"] = area
        g["reviews"] = max(g["reviews"], reviews)

    out = [
        {"name": display_name(g["variants"]), "area": g["area"], "reviews": g["reviews"],
         "count": len(g["sources"]), "sources": sorted(g["sources"])}
        for g in groups
    ]
    # A school with parent ratings outranks one without, however many listicles name the
    # latter. Directory consensus alone fills a post with schools nobody has reviewed, which
    # leaves the parent review section and its graph with nothing real to say. Among schools
    # that both have ratings, or both have none, the old consensus order stands.
    out.sort(key=lambda s: (-min(s["reviews"], 1), -s["reviews"], -s["count"], s["name"]))
    return out


def _same_place(area, group_area):
    """Two entries can be the same school only if nothing says they are in different places.

    Discounting the locality to compare names is what lets "La Martiniere College, Hazratganj"
    meet "La Martiniere College", but on its own it would also fold a chain's Gomti Nagar
    campus into its Kanpur Road one. They are separate schools with separate CMS rows, so a
    stated locality that clashes blocks the merge. A blank locality clashes with nothing.
    """
    if not area or not group_area:
        return True
    return area.strip().lower() == group_area.strip().lower()


def _name_and_area(entry):
    """Accepts a bare name or {"name", "area"}. Returns (name, area), both stripped."""
    if isinstance(entry, dict):
        return (entry.get("name") or "").strip(), (entry.get("area") or "").strip()
    return (entry or "").strip(), ""


def _reviews(entry):
    """How many parent ratings a page credits the school with. 0 when the page shows none.

    Only directory pages that print a rating carry this. It is the signal that separates a
    school parents actually talk about from one that only exists in listicles, so merge()
    keeps the largest count any page gave and ranks on it.
    """
    if not isinstance(entry, dict):
        return 0
    try:
        return max(0, int(entry.get("reviews") or 0))
    except (TypeError, ValueError):
        return 0


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


def cms_name(school, area=""):
    """The plain school name, with short forms expanded. The area is NOT appended.

    Their API adds the area to the slug on create, and their existing rows carry plain
    names, so adding it here would double it. See the module docstring.

    A competitor page that already baked the area into the name keeps it stripped, so
    "Deepalaya School Kalkaji" in Kalkaji becomes "Deepalaya School". That matches what is
    already in their CMS and keeps the slug clean.
    """
    name = expand_short_form(re.sub(r"\s+", " ", school).strip())
    if area:
        name = re.sub(rf"\s*\b{re.escape(area)}\b\s*", " ", name, flags=re.I)
        name = re.sub(r"\s+", " ", name).strip(" ,-")
    return name or expand_short_form(school.strip())


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


EMAIL_DOMAIN = "schools.yellowslate.com"
MAX_LOCAL = 64  # the RFC ceiling on the part before the @


def school_email(name, city="", area=""):
    """city-schoolname-area@schools.yellowslate.com. Pass the cms_name().

    Follows the convention in Yellow Slate's own API docs, whose example is
    delhi-example-school-kalkaji@schools.yellowslate.com. The old rule invented
    gmail.com addresses, which meant creating ~5,000 mailboxes nobody owns inside a
    client's production database.

    The area is included even though their example did not spell it out, because the area
    is what makes it unique: two "Deepalaya School" rows in different Delhi areas are
    different schools, and whether their CMS enforces unique emails is still unanswered
    (message 3, question 1). Mirrors the slug they generate, hyphens instead of the slash.

    A name too long for the 64-character local part is truncated and given a short hash,
    so a very long school name can never collide with another one.
    """
    parts = [p for p in (city, name, area) if p]
    local = slugify("-".join(parts))
    if area and not local.endswith(slugify(area)):
        local = f"{local}-{slugify(area)}"

    if len(local) > MAX_LOCAL:
        from hashlib import blake2s
        digest = blake2s(local.encode("utf-8"), digest_size=3).hexdigest()
        local = local[:MAX_LOCAL - len(digest) - 1].rstrip("-") + "-" + digest
    return f"{local}@{EMAIL_DOMAIN}"
