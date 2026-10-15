"""Work out which locality a school belongs to, for the schools their CMS cannot place itself.

This module used to run for every school, because their API needed a name, a city AND an
area on every lookup. Since their Oct 11, 2026 update, area is optional on
GET /schools/search: name + city finds a school outright and their reply names the area.

So the normal path no longer comes through here at all. clients/cms_api.py searches by name
and city and takes the area from their answer, which is the area their CMS actually holds -
a fact, not a guess. This module is what is left: the fallback for the two cases their
search cannot settle on its own.

  1. A SHARED NAME. "Kidzee" matches five schools in Delhi, "Delhi Public School" more.
     Their API returns the candidates and refuses to guess, so a locality has to come from
     somewhere else before the search can be repeated with it.
  2. A SCHOOL THEY DO NOT HAVE. Creating still needs an area (SCHOOL_NOT_FOUND otherwise),
     because they will not invent a locality for a school they have never seen.

What changed in the rules, and why. The old version of this file refused any area their CMS
did not already know, and the pipeline skipped that school. Two reasons that is now wrong:

  - They create missing areas on demand, so an area they do not know is no longer a dead end.
  - The check itself broke. It sent name="x" with the area and read a 200 as "this area
    exists". After their update an unknown area returns 200 with "area_matched": false,
    so the check said yes to every typo, including the ones it existed to catch.

The replacement is CMS.area_exists(), which lives on the CMS client because it is a question
about their data, and reads "area_matched" rather than the status code. It is advice now
rather than a gate: an area they do not know is still used, and reported as new, since their
CMS matches areas on the exact string and "Tilak Nagar" vs "Tilaknagar" would split one
locality in two. Nothing in this module talks to their API any more - it is text handling
plus one web lookup, so a fake-mode run cannot reach their live CMS through it.

The one hard rule that stays: an area named after its own city is their catch-all and holds
no schools, so it must never be used. That is the bug this module was written for - a city
keyword resolved to area = city, every search missed, and the CMS stage created a duplicate
of a school that already existed under its real locality.
"""

import re

import config
from clients import claude_cli, tavily

LOOKUP_RESULTS = 5


def is_city_area(city, area):
    """An area named after its own city is their catch-all, and no school is filed under it.

    Their search answers for it happily, so it has to be refused by name or it quietly
    reopens the duplicate bug this module exists to close.
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
    """A locality is usable when it is a locality at all and not the city's own catch-all.

    No longer asks whether their CMS knows it. It does not have to: they create the area, and
    exists() reports whether that is about to happen.
    """
    return bool(area) and not is_city_area(city, area)


def resolve(school, city, candidate, blog_area="", lookup=True, among=()):
    """Returns (area, note). An empty area means unresolved: the caller skips that school.

    Order:
      1. what the competitor pages said about this school
      2. the keyword's own area, but only when the pages said nothing. A listicle for one
         area routinely lists schools just outside it, so a page that names a locality is
         evidence the school is NOT in the keyword's area. Overriding it with the keyword
         would file the school somewhere the page says it is not.
      3. one web lookup

    "among" is the areas their CMS offered for a shared name. When it is given, the answer
    has to be one of them: their candidate list is the full set of places a school of that
    name exists, so anything outside it would create a duplicate rather than match a row.
    """
    allowed = {a.strip().lower() for a in among if a and a.strip()}

    def ok(area):
        return bool(area) and usable(city, area) and (not allowed or area.strip().lower() in allowed)

    from_pages = clean(candidate, city)
    if ok(from_pages):
        return from_pages, "from the pages"

    if not from_pages:
        from_keyword = clean(blog_area, city)
        if ok(from_keyword):
            return from_keyword, "from the keyword"

    if not lookup:
        return "", f"pages said {from_pages or 'nothing'!r} and no lookup was run"

    found = lookup_area(school, city)
    if ok(found):
        return found, "from a web lookup"

    said = from_pages or "nothing"
    if allowed:
        offered = ", ".join(sorted(a for a in among if a)) or "none"
        return "", (f"pages said {said!r}, lookup said {found or 'nothing'!r}, and their CMS "
                    f"has this name only in: {offered}")
    if found:
        return "", f"pages said {said!r}, lookup said {found!r}, neither is a usable locality"
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
