"""Find which cities Yellow Slate has already blogged, for the seven city-level keywords.

    py check_blog_coverage.py data/cities_target.txt
    py check_blog_coverage.py data/cities_target.txt --out coverage.csv
    py check_blog_coverage.py data/cities_target.txt --refresh      re-download the sitemap

Reads the live blog sitemap and answers, per city and per keyword, "is this page already
published?". Nothing is written to their CMS and no search API is used.

Why the sitemap and not their API: the pipeline API is write-only for blogs. There is no
GET /blogs, and every GET on the pipeline base except /schools/* answers 401 INVALID_TOKEN
(measured Oct 11, 2026). The public sitemap at /sitemaps/sitemap-blog.xml is the only
complete list of what is live, and robots.txt points to it, so reading it is intended.

The hard part is not fetching, it is telling a CITY page from an AREA page. Their slugs put
the city last, so "best-schools-in-delhi" is the Delhi page while "best-schools-in-adyar-
chennai" is an area page inside Chennai. A substring test would count the second as Chennai
coverage and wrongly mark 400-odd area posts as city posts. So the tail after "-in-" has to
equal the city exactly, once a leading count ("6-", "top-10-") and a trailing decoration
("-2025-26-fees-reviews-admissions-and-more", "-2", "-872458") are removed.

Verdicts per cell:
    done      a live city-level page for that keyword
    open      nothing live, this keyword is free to write

Counted separately, because they are not the keyword asked for but compete with it:
    near      a boarding/residential overlap, or a singular-headed variant

Measured Oct 12, 2026: 2,533 blog URLs, 854 of them listicles, of which only a small share
are city-level. Expect most cells to come back open.
"""

import argparse
import csv
import os
import re
import sys
import urllib.error
import urllib.request

import config
from stages import city as city_stage

SITEMAP_URL = "https://yellowslate.com/sitemaps/sitemap-blog.xml"
CACHE_PATH = os.path.join(config.DATA_DIR, "sitemap-blog.xml")

DONE, OPEN, NEAR = "done", "open", "near"

# The seven keywords, in the order the user gave them, each with the slug heads that mean the
# same page. Singular heads are real: they have published "best-boarding-school-in-navi-mumbai"
# and "best-school-in-..." alongside the plural ones.
KEYWORDS = [
    ("best schools in",               ["best-schools-in", "best-school-in"]),
    ("best cbse schools in",          ["best-cbse-schools-in", "best-cbse-school-in"]),
    ("best icse schools in",          ["best-icse-schools-in", "best-icse-school-in"]),
    ("best igcse schools in",         ["best-igcse-schools-in", "best-igcse-school-in"]),
    ("best ib schools in",            ["best-ib-schools-in", "best-ib-school-in"]),
    ("best international schools in", ["best-international-schools-in", "best-international-school-in"]),
    ("best residential schools in",   ["best-residential-schools-in", "best-residential-school-in"]),
]

# "Boarding" and "residential" are the same search intent in Indian school search, and they
# have 37 boarding posts against 9 residential ones. A boarding page in the city does not
# make the residential keyword done, but writing over it splits your own ranking, so it is
# reported as a near miss for a human to judge rather than counted either way.
NEAR_HEADS = {
    "best residential schools in": [
        "best-boarding-schools-in", "best-boarding-school-in",
        "best-cbse-boarding-schools-in", "best-international-boarding-schools-in",
        "best-girls-boarding-schools-in", "best-boys-boarding-schools-in",
    ],
}

# A leading count: "6-best-schools-in-...", "top-10-best-schools-in-...".
COUNT_PREFIX = re.compile(r"^(?:top-)?\d+-|^top-\d+-")

# Tokens that are decoration on the end of a slug, not part of a place name. Stripped from the
# right, repeatedly, so "baranagar-kolkata-2025-26-fees-reviews-admissions-and-more-2" reduces
# to "baranagar-kolkata". Pure digits cover both years and their dedupe ids ("-2", "-872458").
DECOR_TOKENS = {
    "fees", "fee", "fees-structure", "reviews", "review", "admissions", "admission",
    "and", "more", "facility", "facilities", "details", "detail", "info", "information",
    "guide", "list", "updated", "latest", "ranking", "rankings", "rated", "top",
}

# Their CMS treats these as the same place, but they are separate pages for blogging: a
# Secunderabad post is not the Hyderabad post. Dropped from a city's match list unless the
# city asked about IS that name. See stages/city.py GROUPS, which is deliberately loose.
NOT_THE_SAME_PAGE = {"secunderabad", "new bombay"}


def slugify(name):
    """'Navi Mumbai' -> 'navi-mumbai'. Matches how their slugs are built."""
    out = re.sub(r"[^a-z0-9]+", "-", (name or "").lower())
    return out.strip("-")


def strip_decoration(tail):
    """Drop trailing year/fees/reviews/id noise. Returns the place part of a slug tail."""
    parts = [p for p in tail.split("-") if p]
    while parts:
        last = parts[-1]
        if last in DECOR_TOKENS or last.isdigit():
            parts.pop()
            continue
        break
    return "-".join(parts)


def fetch_sitemap(refresh=False):
    """The blog sitemap XML, cached on disk so repeat runs cost nothing."""
    if os.path.exists(CACHE_PATH) and not refresh:
        with open(CACHE_PATH, encoding="utf-8") as fh:
            return fh.read(), f"cached {CACHE_PATH}"

    request = urllib.request.Request(
        SITEMAP_URL,
        # Their CDN answers 403 to the default urllib agent.
        headers={"User-Agent": "Mozilla/5.0 (yellow-slate-pipeline coverage check)"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        text = response.read().decode("utf-8", "replace")

    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as fh:
        fh.write(text)
    return text, f"downloaded {SITEMAP_URL}"


def blog_slugs(xml):
    """Every /blog/<slug> in the sitemap, lowercased. Their slugs are not consistently cased."""
    found = re.findall(r"<loc>\s*([^<\s]+?)\s*</loc>", xml)
    out = set()
    for url in found:
        match = re.search(r"/blog/([^/?#]+)", url)
        if match:
            out.add(match.group(1).lower().rstrip("/"))
    return out


def index_listicles(slugs):
    """{head: {place: slug}} - for each listicle head, the place each live page covers.

    Built once, so the 330x7 grid is 2,310 dict lookups rather than a scan of 2,533 slugs.
    """
    heads = {h for _, hs in KEYWORDS for h in hs}
    heads |= {h for hs in NEAR_HEADS.values() for h in hs}
    index = {head: {} for head in heads}

    for slug in slugs:
        bare = COUNT_PREFIX.sub("", slug)
        for head in heads:
            if not bare.startswith(head + "-"):
                continue
            place = strip_decoration(bare[len(head) + 1:])
            if place:
                # Keep the shortest slug for a place: it is the clean city URL, not a variant.
                kept = index[head].get(place)
                if kept is None or len(slug) < len(kept):
                    index[head][place] = slug
            break
    return index


def match_places(city):
    """Slugs this city could legitimately appear as, best first."""
    out = []
    for name in city_stage.variants(city):
        if name.lower() in NOT_THE_SAME_PAGE and slugify(name) != slugify(city):
            continue
        place = slugify(name)
        if place and place not in out:
            out.append(place)
    return out


def check_city(city, index):
    """{keyword: (verdict, slug, note)} for one city."""
    places = match_places(city)
    result = {}

    for keyword, heads in KEYWORDS:
        hit, note = "", ""
        for place in places:
            for head in heads:
                slug = index[head].get(place)
                if slug:
                    hit = slug
                    if place != places[0]:
                        note = f"published as {place!r}, not {slugify(city)!r}"
                    break
            if hit:
                break

        if hit:
            result[keyword] = (DONE, hit, note)
            continue

        # Nothing for the keyword itself. Is there a competing page?
        for place in places:
            for head in NEAR_HEADS.get(keyword, []):
                slug = index[head].get(place)
                if slug:
                    result[keyword] = (NEAR, slug, f"{head.replace('-', ' ')} already exists")
                    break
            if keyword in result:
                break
        else:
            result[keyword] = (OPEN, "", "")

    return result


def http_exists(slug, timeout=20):
    """True if /blog/<slug> is a real post. None if the check itself failed.

    Measured Oct 12, 2026: a live post answers 200, and a slug with no post answers 307 to
    /home. So "does this URL redirect" is the test, which is why redirects are not followed.
    """
    url = f"https://yellowslate.com/blog/{slug}"
    request = urllib.request.Request(url, method="HEAD",
                                     headers={"User-Agent": "Mozilla/5.0 (yellow-slate-pipeline coverage check)"})

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **kw):
            return None

    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status == 200
    except urllib.error.HTTPError as exc:
        if exc.code in (301, 302, 303, 307, 308, 404, 410):
            return False
        return None
    except Exception:
        return None


def verify_over_http(cities, index, workers=8):
    """Ask the site directly about every city-level URL, to catch posts the sitemap omits.

    Returns (extra, failed): extra is [(city, keyword, slug)] that answered 200 although the
    sitemap did not list them; failed is the checks that errored.
    """
    import concurrent.futures

    jobs = []
    for city in cities:
        places = match_places(city)
        for keyword, heads in KEYWORDS:
            for place in places:
                for head in heads:
                    if index[head].get(place):     # sitemap already proves this one
                        continue
                    jobs.append((city, keyword, f"{head}-{place}"))

    extra, failed = [], []
    print(f"  checking {len(jobs)} candidate URLs over HTTP with {workers} workers...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(http_exists, slug): (city, keyword, slug)
                   for city, keyword, slug in jobs}
        for done, future in enumerate(concurrent.futures.as_completed(futures), 1):
            city, keyword, slug = futures[future]
            result = future.result()
            if result is True:
                extra.append((city, keyword, slug))
            elif result is None:
                failed.append((city, keyword, slug))
            if done % 500 == 0:
                print(f"    ... {done}/{len(jobs)}", file=sys.stderr)
    return extra, failed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path", help="a .txt of cities, one per line, or a .csv with a City column")
    parser.add_argument("--out", help="write the full city x keyword grid to this CSV")
    parser.add_argument("--refresh", action="store_true", help="re-download the sitemap")
    parser.add_argument("--http", action="store_true",
                        help="also ask the site about every URL the sitemap says is free")
    args = parser.parse_args()

    if not os.path.exists(args.path):
        raise SystemExit(f"No such file: {args.path}")

    from check_cities import read_cities
    cities = read_cities(args.path)
    if not cities:
        raise SystemExit(f"No cities found in {args.path}")

    xml, source = fetch_sitemap(args.refresh)
    slugs = blog_slugs(xml)
    index = index_listicles(slugs)
    listicle_total = sum(len(v) for v in index.values())

    print(f"  sitemap: {source}")
    print(f"  {len(slugs)} blog URLs live, {listicle_total} of them city/area listicles")
    print(f"  {len(cities)} cities x {len(KEYWORDS)} keywords = {len(cities) * len(KEYWORDS)} cells\n")

    rows, done_rows, near_rows = [], [], []
    fully_open, partly_done = [], []

    for city in cities:
        result = check_city(city, index)
        verdicts = [result[kw][0] for kw, _ in KEYWORDS]
        row = {"City": city}
        for keyword, _ in KEYWORDS:
            verdict, slug, note = result[keyword]
            row[keyword] = verdict
            if verdict == DONE:
                done_rows.append((city, keyword, slug, note))
            elif verdict == NEAR:
                near_rows.append((city, keyword, slug, note))
        row["Open count"] = verdicts.count(OPEN)
        rows.append(row)

        if DONE in verdicts:
            partly_done.append((city, verdicts.count(DONE)))
        else:
            fully_open.append(city)

    print(f"  {len(fully_open)} cities with NO city-level page for any of the 7 keywords")
    print(f"  {len(partly_done)} cities with at least one of the 7 already published")
    print(f"  {len(done_rows)} of {len(cities) * len(KEYWORDS)} cells already done\n")

    if done_rows:
        print("-" * 78)
        print("  Already published (do not rewrite)")
        print("-" * 78)
        for city, keyword, slug, note in sorted(done_rows):
            tail = f"   [{note}]" if note else ""
            print(f"  {city:<22} {keyword:<32} /blog/{slug}{tail}")

    if near_rows:
        print("\n" + "-" * 78)
        print("  Near misses - same intent, different wording. Your call.")
        print("-" * 78)
        for city, keyword, slug, note in sorted(near_rows):
            print(f"  {city:<22} {keyword:<32} /blog/{slug}")

    if partly_done:
        print("\n" + "-" * 78)
        print("  Cities already partly covered")
        print("-" * 78)
        for city, count in sorted(partly_done, key=lambda r: -r[1]):
            print(f"  {city:<22} {count} of 7 done, {7 - count} open")

    if args.http:
        print("\n" + "-" * 78)
        print("  Direct HTTP check - does the sitemap miss anything?")
        print("-" * 78)
        extra, failed = verify_over_http(cities, index)
        if extra:
            print(f"  {len(extra)} live pages the sitemap did NOT list:")
            for city, keyword, slug in sorted(extra):
                print(f"    {city:<22} {keyword:<32} /blog/{slug}")
            print("  Treat these as done. The grid above understates coverage.")
        else:
            print("  None. Every page the sitemap calls free really is free.")
        if failed:
            print(f"  {len(failed)} checks could not be completed (network): "
                  f"{', '.join(s for _, _, s in failed[:5])}...")

    if args.out:
        fields = ["City"] + [kw for kw, _ in KEYWORDS] + ["Open count"]
        with open(args.out, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        print(f"\n  wrote {len(rows)} rows to {args.out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
