"""Stage 1: pick candidate schools for a keyword, the way Harshit did it by hand.

Google the keyword -> read the top competitor pages -> Claude pulls the school list
from each page -> count how many pages list each school. Schools most competitors
agree on rank first. Harshit then checks Semrush volume by hand and ticks 8-12.

Schools that carry parent ratings rank above schools that do not, however many competitor
pages list the latter. See RATED below for why.
"""

import config
from clients import claude_cli, tavily
from stages.names import merge

EXCLUDE = ["yellowslate.com", "youtube.com", "facebook.com", "instagram.com", "quora.com", "reddit.com"]
MAX_PAGES = 8
PAGE_CHARS = 12000  # per page, keeps the prompt well inside one headless run
SHORTLIST = 15

# Directories that carry a city's whole school list WITH each school's locality. Searched
# separately and put first, because they rarely rank for "best schools in X" and the pages
# that do rank often carry no locality at all. Measured on Kolar, Oct 15 2026: the eight
# ranking pages yielded no locality for 9 of 15 schools and leaked in Bhopal's Kolar Road
# and Bangalore boarding schools, while careers360's "Schools in Kolar" page listed 42
# schools each with its own town. A missing locality is what makes the cms stage drop a
# school, so this is the cheapest fix for it.
PREFERRED = ["school.careers360.com", "justdial.com"]
PREFERRED_PER_DOMAIN = 2  # kept per domain, so neither can take the other's slots
PREFERRED_PROBE = 5  # asked of Tavily per domain, larger than we keep - see below

# Searched one domain at a time, not in one search with both included. Measured on Kolar,
# Oct 15 2026: include=PREFERRED with both domains and max_results=3 returned justdial's
# Kolar page plus two careers360 SCHOOL pages (christ-international-school-alambady-kolar,
# gnana-jyothi-school-mulbagal-kolar), which carry one locality each and no list at all.
# Tavily ranks freely inside the included domains, so careers360 lost two of the three
# shared slots to single schools - the city list this whole block exists for never arrived.
# include=["school.careers360.com"] alone with max_results=5 returned five "schools in
# Kolar" city lists instead (kseeb-, cbse-, karnataka-board-pue-, central-government-,
# day-cum-boarding-), top to bottom. A per-domain allowance is therefore enough on its own:
# nothing has to rank list-shaped paths above school ones, so nothing does.
#
# PREFERRED_PROBE is larger than PREFERRED_PER_DOMAIN because include is sensitive to the
# result count rather than a top-N of one fixed list: that same careers360 search returned
# 0 hits at max_results=3 and 5 hits at max_results=5 the same day. So ask for 5, keep 2.

# Directories that print a parent rating and a rating count next to each school. Without one
# of these in the pages, every candidate arrives with no review signal and the picker has no
# way to tell a school parents talk about from one that only exists in listicles. Measured on
# Kolar, Oct 15 2026: the ten schools picked without it had 9 Google ratings between them and
# no Justdial listing at all, while Justdial's own Kolar page listed 23 schools with ratings
# and Google Maps showed four Kolar schools carrying 143 to 195 reviews each. That is what
# left nine of ten parent review graphs empty.
RATED = ["justdial.com"]


def _urls(query):
    """Up to MAX_PAGES pages to read: the PREFERRED directories first, then what ranks.

    One search per preferred domain, each keeping PREFERRED_PER_DOMAIN pages, because a
    single search with both domains included lets Tavily's ranking hand one domain the
    other's slots - see PREFERRED above for the numbers. The preferred ones go first so a
    long page never pushes them out of the prompt, and they only take the slots they fill:
    a directory with nothing for this city costs nothing. A failure in one domain is not a
    failed pick, so it is swallowed and the other domain and the ranking pages carry on.
    """
    urls = []
    for domain in PREFERRED:
        try:
            hits = [r["url"] for r in tavily.search(query, max_results=PREFERRED_PROBE,
                                                    include=[domain])]
        except tavily.TavilyError:
            continue
        for url in hits[:PREFERRED_PER_DOMAIN]:
            if url not in urls and len(urls) < MAX_PAGES:
                urls.append(url)

    for url in (r["url"] for r in tavily.search(query, max_results=10, exclude=EXCLUDE)):
        if len(urls) >= MAX_PAGES:
            break
        if url not in urls:
            urls.append(url)
    return urls


def _extract(urls):
    """Read the pages. Anything the basic extract lost is re-read at advanced depth.

    Tavily's basic extract gives a page about ten seconds and clients/tavily.py leaves a URL
    that misses it out of the result, with no error. Measured on Kolar, Oct 15 2026: Justdial
    was first in this list and came back "Request timed out", so the only page in the run
    that printed a rating count per school never reached the extractor and every candidate
    arrived with reviews = 0. The same page at advanced depth returned in full, with ten
    schools, their ratings and their localities.

    Retrying only the lost URLs keeps the advanced surcharge off the pages that worked, and
    nothing is retried at all on a clean run. The retry is swallowed: pages that did arrive
    are still a usable pick.
    """
    pages = {u: body for u, body in tavily.extract(urls).items() if body.strip()}
    missing = [u for u in urls if u not in pages]
    if missing:
        try:
            pages.update({u: body for u, body in tavily.extract(missing, depth="advanced").items()
                          if body.strip()})
        except tavily.TavilyError:
            pass
    return pages


def candidates(keyword, city=""):
    """Returns (shortlist, pages_read). Raises TavilyError / ClaudeError on failure."""
    query = f"{keyword} {city}".strip() if city and city.lower() not in keyword.lower() else keyword
    urls = _urls(query)
    if not urls:
        return [], 0

    pages = _extract(urls)
    if not pages:
        return [], 0

    blob = "\n\n".join(f"=== PAGE: {u} ===\n{body[:PAGE_CHARS]}" for u, body in pages.items())
    prompt = config.read_prompt("pick_extract.md").format(keyword=keyword, pages=blob)
    answer = claude_cli.run_json(prompt, max_turns=2, timeout=600)

    per_page = {p.get("url", f"page{i}"): p.get("schools", []) for i, p in enumerate(answer.get("pages", []))}
    return merge(per_page, city)[:SHORTLIST], len(pages)
