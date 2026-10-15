"""Find the spelling of a city that Yellow Slate's CMS actually accepts.

Why this cannot be a lookup table. Their CMS has no rule about city names. Measured against
the live API on Oct 11, 2026, across 32 old/new name pairs:

    their CMS uses the NEW name:  14      Bengaluru, Gurugram, Mumbai, Kolkata, Chennai...
    their CMS uses the OLD name:  10      Mysore, Vizag, Allahabad, Trichy, Calicut...
    either one works:              3      Trivandrum, Belgaum, Shimoga
    the city is missing entirely:  5      Thane, Hubli, Pondicherry, Panaji, Alleppey

So "use the official modern name" is wrong ten times out of thirty-two, and the table this
module replaces got three of them backwards: it rewrote "Mysore" to "Mysuru" and "Vizag" to
"Visakhapatnam", which both 404, turning two working cities into unknown ones. A table that
is confidently wrong is worse than no table, because the keyword looks blocked on their side.

So: ask them. Their city field is case-insensitive and trims whitespace (measured), but the
spelling has to be exact, and an unknown city returns 404 UNKNOWN_CITY with no suggestions.
This module generates the handful of spellings a city might go by and keeps whichever one
their API answers to. One cheap GET per spelling tried, cached, so a 200-city list costs a
few hundred calls once rather than a wrong answer forever.

GROUPS below is direction-free on purpose: it says "these names mean the same place", and
their API decides which one is right. Adding a pair is safe. Guessing a winner is not.
"""

import re

# Names for one place, in no particular order of authority. Their CMS picks the winner.
# Grown from the Oct 11, 2026 measurement plus the usual Indian renames and short forms.
GROUPS = [
    ("Bangalore", "Bengaluru"),
    ("Bombay", "Mumbai"),
    ("Calcutta", "Kolkata"),
    ("Madras", "Chennai"),
    ("Mysore", "Mysuru"),
    ("Gurgaon", "Gurugram"),
    ("Poona", "Pune"),
    ("Baroda", "Vadodara"),
    ("Cochin", "Kochi", "Ernakulam"),
    ("Trivandrum", "Thiruvananthapuram"),
    ("Vizag", "Visakhapatnam", "Vishakhapatnam"),
    ("Allahabad", "Prayagraj"),
    ("Trichy", "Tiruchirappalli", "Trichinopoly"),
    ("Mangalore", "Mangaluru"),
    ("Belgaum", "Belagavi"),
    ("Hubli", "Hubballi", "Hubli-Dharwad"),
    ("Gulbarga", "Kalaburagi"),
    ("Shimoga", "Shivamogga"),
    ("Tumkur", "Tumakuru"),
    ("Bellary", "Ballari"),
    ("Bijapur", "Vijayapura"),
    ("Calicut", "Kozhikode"),
    ("Trichur", "Thrissur"),
    ("Alleppey", "Alappuzha"),
    ("Quilon", "Kollam"),
    ("Palghat", "Palakkad"),
    ("Cannanore", "Kannur"),
    ("Simla", "Shimla"),
    ("Panjim", "Panaji"),
    ("Jubbulpore", "Jabalpur"),
    ("Banaras", "Benares", "Varanasi", "Kashi"),
    ("Cawnpore", "Kanpur"),
    ("Pondicherry", "Puducherry"),
    ("Waltair", "Vizag"),
    ("New Delhi", "Delhi"),
    ("Secunderabad", "Hyderabad"),
    ("Navi Mumbai", "New Bombay"),
]

_BY_NAME = {}
for group in GROUPS:
    for member in group:
        _BY_NAME.setdefault(member.lower(), set()).update(group)

# A state or country tacked onto the city, which their city field will not match.
TRAILING = re.compile(
    r"(?i),?\s*\b(india|uttar pradesh|u\.?p\.?|maharashtra|karnataka|haryana|punjab|rajasthan|"
    r"gujarat|tamil nadu|t\.?n\.?|telangana|andhra pradesh|a\.?p\.?|kerala|west bengal|w\.?b\.?|"
    r"madhya pradesh|m\.?p\.?|bihar|odisha|orissa|assam|jharkhand|chhattisgarh|uttarakhand|"
    r"himachal pradesh|h\.?p\.?|goa|delhi ncr|ncr|nct)\b\s*$")


def variants(city):
    """Spellings to try for one city, best first. Always starts with the city as given.

    Mechanical tidying first, because it is free and fixes the common sheet mess: a trailing
    state ("Pune, Maharashtra"), doubled spaces, a hyphen where a space belongs. Then the
    other names for the same place out of GROUPS.
    """
    city = (city or "").strip()
    if not city:
        return []

    out = [city]

    def add(name):
        name = re.sub(r"\s+", " ", (name or "")).strip(" ,-")
        if name and name.lower() not in {o.lower() for o in out}:
            out.append(name)

    bare = TRAILING.sub("", city).strip(" ,-")
    add(bare)
    add(bare.replace("-", " "))
    add(bare.replace(".", ""))

    # every other name this place goes by, for each spelling we have arrived at so far
    for known in list(out):
        for other in sorted(_BY_NAME.get(known.lower(), ())):
            add(other)
    return out


def resolve(cms, city):
    """Returns (spelling their CMS accepts, note). An empty string means they do not have it.

    The note is for a human: it says which spelling won and whether it differs from the input,
    so a 200-city list can be read at a glance instead of diffed.
    """
    tried = variants(city)
    if not tried:
        return "", "no city given"

    for candidate in tried:
        if cms.city_exists(candidate):
            if candidate.strip().lower() == (city or "").strip().lower():
                return candidate, ""
            return candidate, f"their CMS spells it {candidate!r}, not {city!r}"

    return "", (f"their CMS has none of: {', '.join(repr(t) for t in tried)}. "
                f"Ask Yellow Slate to add the city - their add-area form cannot.")
