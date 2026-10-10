"""Check every keyword's city and area against their CMS before a single blog is written.

    py preflight_keywords.py keywords.csv
    py preflight_keywords.py keywords.csv --out gaps.csv

Input: a CSV with a Keyword column and a City column. An Area column is used if present,
otherwise the area is read out of the keyword ("schools in Kalkaji" -> "Kalkaji").

Why this exists. POST /blogs takes the KEYWORD's own city and area, and 404s when either is
not in their CMS. So this checks the pair the blog draft itself will be created with. The
schools inside the blog are a separate matter: each one is filed under its own locality by
stages/area.py, so a keyword no longer stands or falls on one area.

For a city-level keyword that pair is the city twice over ("best schools in Lucknow" ->
city Lucknow, area Lucknow). That passes, because an area named after its own city exists in
their CMS. It is empty of schools, which is why nothing else may use it, but it is valid
here, and the draft needs it to be.

Measured Oct 10, 2026, roughly one in five well-known areas does not resolve, and Noida was
2 of 8. On 600 keywords that is worth knowing in two minutes rather than discovering in week 6.

A missing AREA stops that keyword's draft, and is not a dead end. Add it by hand in the CRM,
then rerun this:

    https://crm.yellowslate.com/admin/areas

The form needs the area name, the city (picked from a dropdown) and a latitude and longitude,
so budget a minute per area to look the coordinates up.

A missing CITY is the harder one. The city is a dropdown on that form, so a city that is not
already in their CMS cannot be added from there. Those pairs still go to Yellow Slate's team.

Output is that worklist, split into the two kinds.

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

# Their CMS uses the official name. A keyword list written by a human will not.
ALIASES = {
    "bangalore": "Bengaluru",
    "gurgaon": "Gurugram",
    "bombay": "Mumbai",
    "calcutta": "Kolkata",
    "madras": "Chennai",
    "mysore": "Mysuru",
    "pondicherry": "Puducherry",
    "trivandrum": "Thiruvananthapuram",
    "baroda": "Vadodara",
    "poona": "Pune",
    "cochin": "Kochi",
    "vizag": "Visakhapatnam",
    "new delhi": "Delhi",
}

OK, RENAME, NO_AREA, NO_CITY, ERROR = "ok", "rename", "no area", "no city", "error"


def area_from_keyword(keyword):
    """'schools in Hauz Khas' -> 'Hauz Khas'. Falls back to the whole keyword."""
    text = re.sub(r"(?i)^\s*(best|top)\s+", "", keyword.strip())
    text = re.sub(r"(?i)^\s*\d+\s+", "", text)
    match = re.search(r"(?i)\bschools?\s+in\s+(.+)$", text)
    area = (match.group(1) if match else text).strip()
    area = re.sub(r"\s*,.*$", "", area)            # 'Kalkaji, Delhi' -> 'Kalkaji'
    return re.sub(r"\s+", " ", area).strip(" -")


def probe(city, area):
    """Returns (status, message). A 200 means both the city and the area exist."""
    try:
        ys_http.call("GET", "schools/search",
                     params={"name": "x", "city": city[:100], "area": area[:100]})
        return 200, ""
    except ys_http.UnknownPlace as exc:
        return 404, str(exc)
    except ys_http.YSApiError as exc:
        return getattr(exc, "status", 0) or 0, str(exc)


def classify(city, area):
    """Returns (verdict, city_used, note)."""
    status, message = probe(city, area)
    if status == 200:
        return OK, city, ""

    if status == 404:
        alias = ALIASES.get(city.strip().lower())
        if alias and alias.lower() != city.strip().lower():
            alias_status, alias_message = probe(alias, area)
            if alias_status == 200:
                return RENAME, alias, f"use {alias!r}, not {city!r}"
            message = alias_message or message
        if "Unknown city" in message:
            return NO_CITY, city, message
        return NO_AREA, city, message

    return ERROR, city, message


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

    results = []
    counts = Counter()
    for index, ((city, area), keywords) in enumerate(sorted(pairs.items()), 1):
        verdict, city_used, note = classify(city, area)
        counts[verdict] += 1
        results.append({"City": city, "Area": area, "Verdict": verdict,
                        "Use city": city_used, "Keywords": len(keywords),
                        "Example keyword": keywords[0], "Note": note})
        if verdict != OK:
            print(f"  {verdict:<8} {city:<18} {area:<24} ({len(keywords)} kw)  {note[:60]}")
        if index % 50 == 0:
            print(f"  ... {index}/{len(pairs)}", file=sys.stderr)

    blocked = sum(r["Keywords"] for r in results if r["Verdict"] in (NO_AREA, NO_CITY))
    print("\n" + "-" * 78)
    for verdict in (OK, RENAME, NO_AREA, NO_CITY, ERROR):
        if counts[verdict]:
            print(f"  {verdict:<8} {counts[verdict]:>4} pairs")
    print("-" * 78)
    print(f"  {blocked} of {len(rows)} keywords need a city or area added first "
          f"({100 * blocked / len(rows):.0f}%)")
    if counts[RENAME]:
        print(f"  {counts[RENAME]} pairs work under a different city name. The pipeline should use 'Use city'.")

    if args.out:
        gaps = [r for r in results if r["Verdict"] != OK]
        with open(args.out, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(results[0]))
            writer.writeheader()
            writer.writerows(gaps or results)
        print(f"\n  wrote {len(gaps)} rows to {args.out}")
        print("  'no area' rows: add them at https://crm.yellowslate.com/admin/areas")
        print("  'no city' rows: that form cannot add a city, so these go to their team")

    return 0


if __name__ == "__main__":
    sys.exit(main())
