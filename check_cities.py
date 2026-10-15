"""Work out the spelling Yellow Slate's CMS accepts for each city on a list.

    py check_cities.py cities.txt                    one city per line
    py check_cities.py keywords.csv                  a CSV with a City column
    py check_cities.py cities.txt --out city_map.csv

Run this before adding a batch of new cities to the keyword sheet. It asks their API, one
city at a time, and prints three groups:

    ok        the spelling as given is theirs, nothing to do
    rename    they spell it differently - use the "Their spelling" column in the sheet
    missing   they do not have the city under any name we know. Their add-area form cannot
              add a city, so these go to Yellow Slate's team before the keywords can run.

Why this exists rather than a lookup table: their CMS has no rule about city names. Measured
Oct 11, 2026, it uses the modern name 14 times out of 32 pairs ("Bengaluru", "Gurugram") and
the old one 10 times ("Mysore", "Vizag", "Allahabad", "Trichy"). The table this replaced had
three backwards and turned two working cities into unknown ones. See stages/city.py.

Cost is one or two calls per city, a few hundred for 200 cities, against a limit of 300 a
minute. Nothing is written to their CMS.
"""

import argparse
import csv
import os
import sys

from clients.cms_api import ApiCMS
from clients.cms_base import CMSError
from stages import city as city_stage

OK, RENAME, MISSING = "ok", "rename", "missing"


def read_cities(path):
    """One city per line, or the City column of a CSV. Keeps the first spelling of each."""
    seen, out = set(), []

    def add(name):
        name = (name or "").strip()
        if name and name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)

    if path.lower().endswith(".csv"):
        with open(path, encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh))
        if not rows:
            return out
        column = next((h for h in rows[0] if h and h.lower().strip() == "city"), None)
        if not column:
            raise SystemExit(f"No City column in {path}. Found: {', '.join(rows[0])}")
        for row in rows:
            add(row.get(column))
    else:
        with open(path, encoding="utf-8-sig") as fh:
            for line in fh:
                add(line.split(",")[0])
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path", help="a .txt of cities, one per line, or a .csv with a City column")
    parser.add_argument("--out", help="write the full mapping to this CSV")
    args = parser.parse_args()

    if not os.path.exists(args.path):
        raise SystemExit(f"No such file: {args.path}")

    cities = read_cities(args.path)
    if not cities:
        raise SystemExit(f"No cities found in {args.path}")

    # Always their real API, never the local stand-in: "which spelling do they accept" is a
    # question only their CMS can answer, so CMS_MODE=fake would give a confident wrong answer.
    cms = ApiCMS()
    print(f"{len(cities)} cities to check against their CMS\n")

    results, counts = [], {OK: 0, RENAME: 0, MISSING: 0}
    for index, name in enumerate(cities, 1):
        try:
            theirs, note = city_stage.resolve(cms, name)
        except CMSError as exc:
            print(f"  stopped at {name!r}: {exc}")
            print("  Nothing was written. Fix the error above and run again.")
            return 1

        verdict = OK if theirs and not note else (RENAME if theirs else MISSING)
        counts[verdict] += 1
        results.append({"City": name, "Verdict": verdict,
                        "Their spelling": theirs, "Note": note})
        if verdict != OK:
            print(f"  {verdict:<8} {name:<24} {theirs or '-':<24} {note[:70]}")
        if index % 25 == 0:
            print(f"  ... {index}/{len(cities)}", file=sys.stderr)

    print("\n" + "-" * 78)
    for verdict in (OK, RENAME, MISSING):
        if counts[verdict]:
            print(f"  {verdict:<8} {counts[verdict]:>4} cities")
    print("-" * 78)
    if counts[RENAME]:
        print(f"  {counts[RENAME]} cities need the sheet's City column changed to the "
              f"'Their spelling' value.")
    if counts[MISSING]:
        print(f"  {counts[MISSING]} cities are not in their CMS under any name we know. Send "
              f"that list to Yellow Slate - a city cannot be added from the CRM's own form.")

    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=["City", "Verdict", "Their spelling", "Note"])
            writer.writeheader()
            writer.writerows(results)
        print(f"\n  wrote {len(results)} rows to {args.out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
