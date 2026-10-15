"""Stage 1: pick candidate schools for a keyword, the way Harshit did it by hand.

Google the keyword -> read the top competitor pages -> Claude pulls the school list
from each page -> count how many pages list each school. Schools most competitors
agree on rank first. Harshit then checks Semrush volume by hand and ticks 8-12.

Schools that carry parent ratings rank above schools that do not, however many competitor
pages list the latter. See RATED below for why.
"""

import re

import config
from clients import claude_cli, tavily
from stages.names import merge, normalize

EXCLUDE = ["yellowslate.com", "youtube.com", "facebook.com", "instagram.com", "quora.com", "reddit.com"]
MAX_PAGES = 10
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
#
# Justdial alone is not enough, and relying on it is what left Kalkaji with no signal at all.
# Measured on Kalkaji, Oct 15 2026: both of its Kalkaji pages failed at BOTH depths - "Request
# timed out" at basic, "Failed to fetch url" at advanced, twice. Pune's two list pages failed
# the same way and Hauz Khas returned no Justdial hits at all. Only Kolar's bare
# /Kolar/Schools/ page was fetchable, so the advanced retry rescued one page and was mistaken
# for a general fix. Edustoke carries the same signal and does extract: its Kalkaji page came
# back in full at 62,172 characters printing "4.0(9 votes)" next to nearly every school on the
# shortlist, and ezyschooling printed "5.0  1 Review" for some. They get a slot each so a
# rated page is in the set even when Justdial is unreachable.
RATED = ["edustoke.com", "ezyschooling.com", "justdial.com"]
RATED_PER_DOMAIN = 1  # one list page each is enough; the counts are read off it directly


def searched_domains():
    """Every domain given a slot of its own, in the order they are searched."""
    return PREFERRED + [d for d in RATED if d not in PREFERRED]


# A directory earns its slot by listing a city, not one school. Measured on Kalkaji, Oct 15
# 2026: include=["school.careers360.com"] returned school-of-excellence-kalkaji-new-delhi and
# government-co-educational-senior-secondary-school-kalkaji-new-delhi FIRST, then
# schools-in-delhi and hindi-medium-schools-in-delhi. Keeping the top two spends both slots on
# single-school pages, which carry one locality each and no list - the same loss the
# per-domain search was built to prevent, which it did for Kolar but not here. So list-shaped
# URLs are kept first, and a single-school page only fills a slot no list wanted.
LIST_SHAPED = re.compile(r"schools?-in-", re.I)


def _lists_first(urls):
    """List pages, then the rest, each keeping the order the search gave."""
    return ([u for u in urls if LIST_SHAPED.search(u)]
            + [u for u in urls if not LIST_SHAPED.search(u)])


# Reading the rating count off the page itself, instead of asking the model for it.
#
# Measured on Kalkaji, Oct 15 2026. Every part of the model path worked: the prompt asks for
# the count, the extractor read "4.0(9 votes)" correctly when tested (Kalka 9, Deepalaya 7,
# Sri Sathya Sai 6), _reviews() parsed it and merge() kept the max. The run still wrote
# reviews = 0 for all 15 candidates, because PAGE_CHARS cuts edustoke's 62,172-character page
# to its first 12,000 - which holds 6 of its 25 vote counts - and Tavily does not always
# return the same rendering of a page twice. A count that only survives if the right rendering
# arrives and the right 19% of it is kept is not a signal, it is luck. This regex reads the
# whole body, cannot be truncated, costs nothing and does not depend on the model noticing.
#
# The rating and its count sit together in every shape seen: "4.0(9 votes)" on edustoke,
# "5.0  1 Review" on ezyschooling, and the compact "3.47 votes" edustoke repeats lower down
# (a 3.4 rating with 7 votes).
RATING = re.compile(r"([0-5](?:\.\d)?)\s*\(?\s*(\d{1,6})\s*(?:votes?|ratings?|reviews?)\b\)?", re.I)
LINK = re.compile(r"(?<!!)\[([^\]\[]{3,120})\]\(")
RATING_LOOKBACK = 700  # measured: ezyschooling stacks four links between name and rating
CURRENCY = re.compile(r"[₹$€]")
FEE_LINE = re.compile(r"fees?\b", re.I)  # "MonthlyFees NA" carries no currency sign

# Link text that is a control or a label, not a school. Measured on the real pages, Oct 15
# 2026: taking the nearest link above each rating credited edustoke's "View School" button
# with 7 ratings, and on ezyschooling the "Session: 2027-2028" link sits between a school's
# name and its rating, so that label took the count and 4 of the page's 5 ratings were lost.
BUTTON = re.compile(
    r"^(view|read|see|more|details?|compare|apply|admissions?|session|enquire|enquiry|"
    r"shortlist|download|book|get|contact|brochure|fees?|reviews?|ratings?|photos?|gallery|"
    r"map|directions|know)\b", re.I)


def _link_name(text):
    """The school name a link's text holds, or "" if it holds something else.

    Measured on ezyschooling's Kalkaji page, Oct 15 2026, four shapes sit between a school's
    name and its rating and each one had to be ruled out:
      - "Board:", "Classes:", "Session:" - a colon marks a field label, and no school name
        carries one;
      - "MonthlyFees RS 2.86 K - 3.17 K", and "MonthlyFees NA" when the fee is
        unpublished - the word "fees" marks the line whether or not a currency sign does;
      - "#### Kalkaji, South East Delhi" - an h4 sub-line is the locality, and crediting it
        would invent a school out of a place name;
      - "View School" on edustoke - a button, see BUTTON.
    The name itself is an h3 inside the link text, so the heading marks are stripped off it.
    """
    if ":" in text or CURRENCY.search(text) or FEE_LINE.search(text):
        return ""
    if text.lstrip().startswith("####"):
        return ""  # an h4 is the locality under the name, not the name
    name = text.lstrip("# ").strip()
    if not re.search(r"[a-z]", name, re.I) or BUTTON.match(name):
        return ""
    return name


def page_ratings(body):
    """{normalised school name: how many parent ratings this page credits it with}.

    A school with no ratings is left out rather than recorded as 0: edustoke prints
    "0.0(0 votes)" for a school nobody has rated, and that is an absence, not a count.
    """
    links = [(m.end(), m.group(1).strip()) for m in LINK.finditer(body)]
    out = {}
    for m in RATING.finditer(body):
        count = int(m.group(2))
        if count <= 0:
            continue
        name = ""
        for end, text in links:
            if end > m.start():
                break  # a link that opens after the rating cannot be its name
            if end < m.start() - RATING_LOOKBACK or RATING.search(text):
                continue
            found = _link_name(text)
            if found:
                name = found  # nearest link above it that holds a name
        key = normalize(name) if name else ""
        if key:
            out[key] = max(out.get(key, 0), count)
    return out


def _floor_reviews(per_page, pages):
    """Lift any school the model left unrated to the count its page actually prints.

    A floor, never a cap: a larger number the model found is kept. The counts are pooled
    across pages because a rating count belongs to the school, not to the page that printed
    it, and merge() takes the largest any page gave in any case.
    """
    floor = {}
    for body in pages.values():
        for key, count in page_ratings(body).items():
            floor[key] = max(floor.get(key, 0), count)
    if not floor:
        return
    for schools in per_page.values():
        for school in schools:
            if not isinstance(school, dict):
                continue
            found = floor.get(normalize(school.get("name") or ""), 0)
            if found > (school.get("reviews") or 0):
                school["reviews"] = found


def _urls(query):
    """Up to MAX_PAGES pages to read: the PREFERRED directories first, then what ranks.

    One search per preferred domain, each keeping PREFERRED_PER_DOMAIN pages, because a
    single search with both domains included lets Tavily's ranking hand one domain the
    other's slots - see PREFERRED above for the numbers. The preferred ones go first so a
    long page never pushes them out of the prompt, and they only take the slots they fill:
    a directory with nothing for this city costs nothing. A failure in one domain is not a
    failed pick, so it is swallowed and the other domain and the ranking pages carry on.

    The RATED directories are searched the same way, one slot each, so a page that prints a
    rating count is in the set even when Justdial cannot be fetched. Within a domain the
    list-shaped URLs are kept first - see LIST_SHAPED for the single-school pages that took
    careers360's Kalkaji slots.
    """
    urls = []

    def keep(domain, limit):
        try:
            hits = [r["url"] for r in tavily.search(query, max_results=PREFERRED_PROBE,
                                                    include=[domain])]
        except tavily.TavilyError:
            return
        for url in _lists_first(hits)[:limit]:
            if url not in urls and len(urls) < MAX_PAGES:
                urls.append(url)

    for domain in PREFERRED:
        keep(domain, PREFERRED_PER_DOMAIN)
    for domain in RATED:
        if domain not in PREFERRED:
            keep(domain, RATED_PER_DOMAIN)

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
    _floor_reviews(per_page, pages)
    return merge(per_page, city)[:SHORTLIST], len(pages)
