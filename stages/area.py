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


def places_in(area, city=""):
    """Every place name inside an area string, in the order written. Street junk dropped.

    clean() keeps the last of these, because a page writes an address outward-in and the
    locality is the most specific place in it. Comparing two area strings needs all of them,
    because THEIR area field is not a page address and follows no such order. Measured
    against their live CMS on Oct 19, 2026: row 15236 holds "Kalkaji Extension, Block A
    10,Govindpuri", locality first and the block in the middle, while 12912 holds
    "Bikshapathi Nagar,Hafeezpet" and another row "South Campus,South Moti Bagh", locality
    last.
    """
    text = (area or "").strip()
    if not text:
        return []
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
        part = re.sub(r"(?i)\b(sector)\s*-\s*(\d+)", r"\1 \2", part)
        keep.append(re.sub(r"\s+", " ", part).strip(" -,"))
    return [part for part in keep if part]


def clean(area, city=""):
    """'Vibhuti Khand, Gomti Nagar, Lucknow 226010' -> 'Gomti Nagar'. Locality only.

    Pages write the locality as anything from a bare name to a full postal address, so this
    throws away everything that is not a locality and keeps the last part standing. "Sector 62"
    survives, "Plot 5" does not.
    """
    # the locality is the most specific place name left, which is the last one
    parts = places_in(area, city)
    return parts[-1] if parts else ""


def usable(city, area):
    """A locality is usable when it is a locality at all and not the city's own catch-all.

    No longer asks whether their CMS knows it. It does not have to: they create the area, and
    exists() reports whether that is about to happen.
    """
    return bool(area) and not is_city_area(city, area)


# Address short forms, for comparing two spellings of one locality only. Not for output.
AREA_SHORT = {"rd": "road", "ext": "extension", "extn": "extension", "enc": "enclave",
              "sec": "sector", "gdn": "garden", "gdns": "gardens", "apt": "apartments"}


def _key_of(place):
    """One place name reduced to a comparison key. Never an answer in itself.

    Their CMS and a competitor page write the same place differently: "R.K. Puram" against
    "R. K. Puram", "Mathura Road" against "Mathura Rd". This drops punctuation and expands
    the few address short forms, so the two compare equal.

    It is only ever a key. What goes back to them is their own string, because they match an
    area on the exact characters, and because their spellings follow no rule worth guessing
    at - the point here is to RECOGNISE their spelling, never to correct it.
    """
    words = re.sub(r"[^a-z0-9]+", " ", (place or "").lower()).split()
    return " ".join(AREA_SHORT.get(w, w) for w in words)


def _key(area, city):
    """The comparison key for the one locality in an area string."""
    return _key_of(clean(area, city))


def _keys(area, city=""):
    """A key for every place name in an area string, because their field holds all of them."""
    return [key for key in (_key_of(p) for p in places_in(area, city)) if key]


def _one_place(a, b):
    """True when two place keys name one place: the same words, or a plainer form of them.

    The plainer form is what their area field needs, because it writes a locality out
    further than a page does. Measured Oct 19, 2026: their 15236 is "Kalkaji Extension, ..."
    where every page says "Kalkaji", and reading those as two places is what created the
    duplicate row. So one key being the start of the other is one place.

    A trailing NUMBER is the exception, and not a small one: "Greater Kailash" and "Greater
    Kailash 1" are different localities, as are "Dwarka" and "Dwarka Sector 7". A number is
    how these cities name a block, so an extra word carrying a digit means the two strings
    are about different blocks rather than one place written out further.
    """
    wa, wb = a.split(), b.split()
    if not wa or not wb:
        return False
    short, longer = (wa, wb) if len(wa) <= len(wb) else (wb, wa)
    if longer[:len(short)] != short:
        return False
    return not any(ch.isdigit() for word in longer[len(short):] for ch in word)


def same_place(a, b, city=""):
    """True when two strings name one locality, however each of them spells it.

    Their CMS matches an area on the exact characters, so one locality can sit in it under
    two spellings at once: measured Oct 16, 2026, Delhi has BOTH "R. K. Puram" (three Delhi
    Public School rows) and "R.K. Puram" (empty). Comparing the raw text makes the empty twin
    look like a real locality with no school in it - a new campus - and the answer to that is
    a duplicate row. Comparing the key makes them one place, which is what they are.

    Widened on Oct 19, 2026, after their CMS turned out to hold the same school twice over
    exactly this comparison. Their area field is an address, not a locality: 15236 DEEPALAYA
    SCHOOL sits in "Kalkaji Extension, Block A 10,Govindpuri" and 21497 Sri Satya Sai Vidya
    Vihar School in the same string, while every page says "Kalkaji". Both halves of the old
    comparison were too narrow for that - it read only the LAST place name in each string,
    and it demanded the two be equal. So this now compares every place name in one string
    against every place name in the other, and counts one key as a plainer form of the
    other. Their own area search cannot help here: it matches the exact characters and
    nothing shorter, so scoping to "Kalkaji Extension" comes back area_matched false even
    though "Kalkaji Extension, Block A 10,Govindpuri" is one of their areas.
    """
    return any(_one_place(ka, kb) for ka in _keys(a, city) for kb in _keys(b, city))


def _as_they_spell_it(area, among, city):
    """Their exact string for a locality, when they file it behind a prefix. "" otherwise.

    Some of their areas carry the campus in front of the locality: "South Campus,South Moti
    Bagh", "Todermal Road Area,Mandi House". A competitor page writes the locality alone, so
    the two never match on the raw text even though they are the same place. clean() reduces
    their string to the same locality, which is what makes them comparable.

    What goes back is THEIR string, never the page's. Their CMS matches an area on the exact
    characters, so sending the bare locality would be an area they do not have: since their
    Oct 11, 2026 update that is ignored rather than refused, the search widens to the whole
    city and comes back just as ambiguous as it started. See [the typo trap in] the module
    docstring.

    Only consulted when `among` is given, and only after the plain match has failed, so this
    can turn an unresolved school into a placed one and can never change an existing answer.
    """
    if not _key(area, city):
        return ""
    for theirs in among:
        theirs = (theirs or "").strip()
        if theirs and usable(city, theirs) and same_place(theirs, area, city):
            return theirs
    return ""


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

    spelt = _as_they_spell_it(from_pages, among, city)
    if spelt:
        return spelt, "from the pages, as their CMS spells it"

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
