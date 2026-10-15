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
PREFERRED_SLOTS = 3

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

    The preferred ones go first so a long page never pushes them out of the prompt, and they
    only take the slots they fill - a directory with nothing for this city costs nothing. A
    failure there is not a failed pick, so it is swallowed and the ranking pages carry on.
    """
    try:
        preferred = [r["url"] for r in tavily.search(query, max_results=PREFERRED_SLOTS,
                                                     include=PREFERRED)]
    except tavily.TavilyError:
        preferred = []

    urls = preferred[:PREFERRED_SLOTS]
    for url in (r["url"] for r in tavily.search(query, max_results=10, exclude=EXCLUDE)):
        if len(urls) >= MAX_PAGES:
            break
        if url not in urls:
            urls.append(url)
    return urls


def candidates(keyword, city=""):
    """Returns (shortlist, pages_read). Raises TavilyError / ClaudeError on failure."""
    query = f"{keyword} {city}".strip() if city and city.lower() not in keyword.lower() else keyword
    urls = _urls(query)
    if not urls:
        return [], 0

    pages = tavily.extract(urls)
    pages = {u: body for u, body in pages.items() if body.strip()}
    if not pages:
        return [], 0

    blob = "\n\n".join(f"=== PAGE: {u} ===\n{body[:PAGE_CHARS]}" for u, body in pages.items())
    prompt = config.read_prompt("pick_extract.md").format(keyword=keyword, pages=blob)
    answer = claude_cli.run_json(prompt, max_turns=2, timeout=600)

    per_page = {p.get("url", f"page{i}"): p.get("schools", []) for i, p in enumerate(answer.get("pages", []))}
    return merge(per_page, city)[:SHORTLIST], len(pages)
