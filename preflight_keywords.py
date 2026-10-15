"""Check every keyword's city and area against their CMS before a single blog is written.

    py preflight_keywords.py keywords.csv
    py preflight_keywords.py keywords.csv --out gaps.csv

Input: a CSV with a Keyword column and a City column. An Area column is used if present,
otherwise the area is read out of the keyword ("schools in Kalkaji" -> "Kalkaji").

Why this exists. POST /blogs takes the KEYWORD's own city and area, and 404s when either is
not in their CMS. So this checks the pair the blog draft itself will be created with. The
schools inside the blog are a separate matter: each one is filed under the locality their own
CMS reports for it (stages/cms.py), so a keyword no longer stands or falls on one area.

For a city-level keyword that pair is the city twice over ("best schools in Lucknow" ->
city Lucknow, area Lucknow). That passes, because an area named after its own city exists in
their CMS. It is empty of schools, which is why nothing else may use it, but it is valid
here, and the draft needs it to be.

Measured Oct 10, 2026, roughly one in five well-known areas did not resolve, and Noida was
2 of 8. Their Oct 11, 2026 update makes most of that go away: they create a missing area on
first use, so a locality they do not have is now a note on the run and not a blocked keyword.
There is nothing to add by hand in the CRM any more.

What is worth reading in that list is the SPELLING. Their CMS matches an area on the exact
string, so "Tilak Nagar" and "Tilaknagar" become two separate localities and split one area's
schools between them. A typo used to be caught here as a missing area; now it is accepted and
quietly creates a place.

A missing CITY is the one hard stop left. The city is a dropdown on their add-area form, so a
city that is not already in their CMS cannot be created from here at all. Those pairs still go
to Yellow Slate's team.

Output is that worklist: the cities to chase, and the new localities to proofread.

One gotcha it fixes on its own: their CMS uses official city names. "Bangalore" 404s and
"Bengaluru" works, same for Gurgaon and Gurugram. ALIASES below is retried automatically,
and a keyword that only resolves under the alias is reported as a rename, not a gap.
"""

import argparse
import csv
import re
import sys
from collections import Counter

import config
from clients import ys_http
from clients.cms_api import ApiCMS
from stages import city as city_stage

# The alias table that used to live here is gone, and it was wrong. It assumed their CMS uses
# the official modern name, which it does for "Bengaluru" and "Gurugram" and does NOT for
# "Mysore", "Vizag", "Allahabad", "Trichy" or "Calicut". Three of its thirteen entries pointed
# at a spelling their API 404s on, so it turned two working cities into unknown ones.
# stages/city.py asks them instead, and GROUPS there is direction-free on purpose.

# NO_AREA is gone: an area their CMS does not have is created on first use, so it is a note
# on the run and not a reason to hold a keyword back.
OK, RENAME, NEW_AREA, NO_CITY, ERROR = "ok", "rename", "new area", "no city", "error"


def area_from_keyword(keyword):
    """'schools in Hauz Khas' -> 'Hauz Khas'. Falls back to the whole keyword."""
    text = re.sub(r"(?i)^\s*(best|top)\s+", "", keyword.strip())
    text = re.sub(r"(?i)^\s*\d+\s+", "", text)
    match = re.search(r"(?i)\bschools?\s+in\s+(.+)$", text)
    area = (match.group(1) if match else text).strip()
    area = re.sub(r"\s*,.*$", "", area)            # 'Kalkaji, Delhi' -> 'Kalkaji'
    return re.sub(r"\s+", " ", area).strip(" -")


def probe(city, area):
    """Returns (verdict, message) for one city + area pair, straight off their API.

    Their Oct 11, 2026 update broke the check this used to make. It read a 200 as "their CMS
    knows both the city and the area", which stopped being true: an unknown area now answers
    200 with "area_matched": false and the search quietly widens to the whole city. So a
    typo'd area passed the preflight and the batch ran on it.

    Two signals replace it, both from their reply rather than from the status code:
      - "code": UNKNOWN_CITY is the only hard stop left. A city is a dropdown on their
        add-area form, so a city they do not have cannot be created from here.
      - "area_matched": false means the area is new. That is no longer an error, because
        they create missing areas, but it is worth printing: their CMS matches an area on
        the exact string, so "Tilak Nagar" and "Tilaknagar" become two places.
    """
    try:
        body = ys_http.call("GET", "schools/search",
                            params={"name": "zzqx no such school", "city": city[:100],
                                    "area": area[:100]})
    except ys_http.NotInCms:
        # no school of that name, which is the point of asking. Their 404 body carries no
        # area_matched, so the area cannot be confirmed either way from here.
        return NEW_AREA, "their CMS answered without placing the area"
    except ys_http.UnknownPlace as exc:
        return NO_CITY, str(exc)
    except ys_http.YSApiError as exc:
        if getattr(exc, "code", "") == "UNKNOWN_CITY":
            return NO_CITY, str(exc)
        return ERROR, str(exc)

    matched = body.get("area_matched") if isinstance(body, dict) else None
    if matched is False:
        return NEW_AREA, f"{area!r} is not in their CMS yet and will be created on first use"
    return OK, ""


def classify(cms, city, area):
    """Returns (verdict, city_used, note).

    The city comes first, because an area check against a city their CMS does not have tells
    you nothing. stages/city.py tries the spellings this place goes by and reports the one
    their API answers to, which is as likely to be the old name as the new one.
    """
    theirs, spelling = city_stage.resolve(cms, city)
    if not theirs:
        return NO_CITY, city, spelling

    verdict, message = probe(theirs, area)
    if spelling:
        note = f"{spelling}. {message}" if message else spelling
        return RENAME, theirs, note
    return verdict, theirs, message


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("keywords", help="CSV with Keyword and City columns")
    parser.add_argument("--out", help="write the gap list to this CSV")
    args = parser.parse_args()

    if not config.YS_API_KEY:
        print("No YS_API_KEY in .env.")
        return 1

    with open(args.keywords, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        print(f"{args.keywords} has no rows.")
        return 1

    headers = {h.lower().strip(): h for h in rows[0]}
    if "keyword" not in headers:
        print(f"Need a Keyword column. Found: {', '.join(rows[0])}")
        return 1
    if "city" not in headers:
        print(f"Need a City column. Found: {', '.join(rows[0])}")
        return 1

    kw_col, city_col = headers["keyword"], headers["city"]
    area_col = headers.get("area")

    # one probe per city+area pair, not per keyword, since areas repeat across keywords
    pairs = {}
    for row in rows:
        keyword = (row.get(kw_col) or "").strip()
        city = (row.get(city_col) or "").strip()
        if not keyword or not city:
            continue
        area = (row.get(area_col) or "").strip() if area_col else ""
        area = area or area_from_keyword(keyword)
        pairs.setdefault((city, area), []).append(keyword)

    print(f"{len(rows)} keywords, {len(pairs)} unique city + area pairs to check\n")

    # one client for the whole run, so each city and area is asked about once and cached
    cms = ApiCMS()
    results = []
    counts = Counter()
    for index, ((city, area), keywords) in enumerate(sorted(pairs.items()), 1):
        verdict, city_used, note = classify(cms, city, area)
        counts[verdict] += 1
        results.append({"City": city, "Area": area, "Verdict": verdict,
                        "Use city": city_used, "Keywords": len(keywords),
                        "Example keyword": keywords[0], "Note": note})
        if verdict != OK:
            print(f"  {verdict:<8} {city:<18} {area:<24} ({len(keywords)} kw)  {note[:60]}")
        if index % 50 == 0:
            print(f"  ... {index}/{len(pairs)}", file=sys.stderr)

    blocked = sum(r["Keywords"] for r in results if r["Verdict"] in (NO_CITY, ERROR))
    print("\n" + "-" * 78)
    for verdict in (OK, RENAME, NEW_AREA, NO_CITY, ERROR):
        if counts[verdict]:
            print(f"  {verdict:<9} {counts[verdict]:>4} pairs")
    print("-" * 78)
    print(f"  {blocked} of {len(rows)} keywords are held back by an unknown city "
          f"({100 * blocked / len(rows):.0f}%)")
    if counts[RENAME]:
        print(f"  {counts[RENAME]} pairs work under a different city name. The pipeline should use 'Use city'.")
    if counts[NEW_AREA]:
        print(f"  {counts[NEW_AREA]} pairs name a locality their CMS does not have yet. Not blocked, "
              f"it is created on first use, but read them for typos: a misspelt one becomes a "
              f"second locality and splits that area's schools.")

    if args.out:
        gaps = [r for r in results if r["Verdict"] != OK]
        with open(args.out, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(results[0]))
            writer.writeheader()
            writer.writerows(gaps or results)
        print(f"\n  wrote {len(gaps)} rows to {args.out}")
        print("  'new area' rows: nothing to add by hand any more, just check the spelling")
        print("  'no city' rows: their add-area form cannot add a city, so these go to their team")

    return 0


if __name__ == "__main__":
    sys.exit(main())
