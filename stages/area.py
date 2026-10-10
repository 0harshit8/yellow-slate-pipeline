"""Work out which area each school belongs to, and check that area exists in their CMS.

Why this stage exists. Their API needs a name, a city AND an area on every school lookup:
area is not optional, and there is no city-wide search (verified Oct 10, 2026 - omitting it,
sending it empty and sending "*" are all rejected). So the area has to be known before a
school can be searched for or created.

The pipeline used to take one area per keyword, read out of the keyword text, and use it for
every school in the blog. That works for an area keyword ("best schools in Kalkaji") and is
wrong for a city keyword ("best schools in Lucknow"), which is most of the list. It resolved
to area "Lucknow", and a city-named area is a real but EMPTY area in their CMS:

    Delhi Public School in "Dwarka" -> id 8231
    Delhi Public School in "Rohini" -> id 20698
    Delhi Public School in "Delhi"  -> nothing

So every search missed, and the CMS stage created a fresh duplicate of a school that already
existed under its real locality. A 404 would have been safer: it stops. This did not.

Hence: the area is a fact about the SCHOOL, not about the keyword. The pick stage now reads
each school's locality off the competitor pages, and this module verifies it against their
CMS before anything is created. A locality their CMS does not know is left unresolved, and
the caller skips that school rather than filing it somewhere wrong.
"""

import re

import config
from clients import claude_cli, tavily, ys_http

# (city.lower(), area.lower()) -> bool. Their CMS place list does not change mid-run.
_known = {}

LOOKUP_RESULTS = 5


def known(city, area):
    """True if their CMS knows this city + area pair. Cached, one cheap GET per new pair."""
    city, area = (city or "").strip(), (area or "").strip()
    if not city or not area:
        return False
    cache_key = (city.lower(), area.lower())
    if cache_key in _known:
        return _known[cache_key]
    try:
        ys_http.call("GET", "schools/search",
                     params={"name": "x", "city": city[:100], "area": area[:100]})
        _known[cache_key] = True
    except ys_http.UnknownPlace:
        _known[cache_key] = False
    return _known[cache_key]


def is_city_area(city, area):
    """An area named after its own city is their catch-all, and no school is filed under it.

    It passes the known() check, so it has to be refused by name or it quietly reopens the
    duplicate bug this module exists to close.
    """
    return (city or "").strip().lower() == (area or "").strip().lower()


DROP_WORDS = {"india", "uttar pradesh", "up", "delhi ncr", "ncr", "maharashtra", "karnataka",
              "haryana", "punjab", "rajasthan", "gujarat", "tamil nadu", "telangana", "kerala",
              "west bengal", "madhya pradesh", "bihar", "odisha", "assam", "jharkhand",
              "chhattisgarh", "uttarakhand", "himachal pradesh", "goa", "new delhi"}

STREET_PART = re.compile(r"(?i)^(plot|flat|house|h\.?\s*no|no\.?|shop|khasra|survey|\d+[a-z]?)\b")


def clean(area, city=""):
    """'Vibhuti Khand, Gomti Nagar, Lucknow 226010' -> 'Gomti Nagar'. Locality only.

    Pages write the locality as anything from a bare name to a full postal address, so this
    throws away everything that is not a locality and keeps the last part standing. "Sector 62"
    survives, "Plot 5" does not.
    """
    text = (area or "").strip()
    if not text:
        return ""
    text = re.sub(r"\b\d{6}\b", "", text)                  # pin code
    text = re.sub(r"(?i)\b(near|opp\.?|opposite|behind)\b.*$", "", text)

    keep = []
    for part in (p.strip(" -\t") for p in text.split(",")):
        if not part:
            continue
        low = part.lower()
        if low in DROP_WORDS or (city and low == city.strip().lower()):
            continue
        if STREET_PART.match(part) and not re.match(r"(?i)^sector\b", part):
            continue
        keep.append(part)
    if not keep:
        return ""

    # the locality is the most specific place name left, which is the last one
    text = re.sub(r"(?i)\b(sector)\s*-\s*(\d+)", r"\1 \2", keep[-1])
    return re.sub(r"\s+", " ", text).strip(" -,")


def usable(city, area):
    """An area is usable when their CMS knows it and it is not the city's own catch-all."""
    return bool(area) and not is_city_area(city, area) and known(city, area)


def resolve(school, city, candidate, blog_area="", lookup=True):
    """Returns (area, note). An empty area means unresolved: the caller skips that school.

    Order:
      1. what the competitor pages said about this school
      2. the keyword's own area, but only when the pages said nothing. A listicle for one
         area routinely lists schools just outside it, so a page that names a locality is
         evidence the school is NOT in the keyword's area, even when that locality turns out
         to be missing from their CMS. Overriding it with the keyword would file the school
         somewhere the page says it is not.
      3. one web lookup
    Every option is checked against their CMS first, so a resolved area is always one that
    can be searched and created against.
    """
    from_pages = clean(candidate, city)
    if usable(city, from_pages):
        return from_pages, "from the pages"

    if not from_pages:
        from_keyword = clean(blog_area, city)
        if usable(city, from_keyword):
            return from_keyword, "from the keyword"

    if not lookup:
        return "", f"pages said {from_pages or 'nothing'!r} and no lookup was run"

    found = lookup_area(school, city)
    if usable(city, found):
        return found, "from a web lookup"

    said = from_pages or "nothing"
    if found:
        return "", f"pages said {said!r}, lookup said {found!r}, neither is an area in their CMS"
    return "", f"pages said {said!r}, the lookup found none, so there is no area to file it under"


def lookup_area(school, city):
    """One Tavily search plus one short Claude call. Returns a locality, or "" if unsure."""
    try:
        results = tavily.search(f'"{school}" {city} school address locality',
                                max_results=LOOKUP_RESULTS)
    except Exception:                       # noqa: BLE001 - a failed lookup is not a failed blog
        return ""
    if not results:
        return ""

    blob = "\n\n".join(
        f"=== {r.get('title', '')} ===\n{(r.get('content') or '')[:1200]}" for r in results
    )
    prompt = config.read_prompt("area_lookup.md").format(school=school, city=city, results=blob)
    try:
        answer = claude_cli.run_json(prompt, max_turns=2, timeout=300)
    except Exception:                       # noqa: BLE001 - same
        return ""
    return clean(answer.get("area", ""), city)
