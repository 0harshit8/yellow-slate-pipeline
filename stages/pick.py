"""Stage 1: pick candidate schools for a keyword, the way Harshit did it by hand.

Google the keyword -> read the top competitor pages -> Claude pulls the school list
from each page -> count how many pages list each school. Schools most competitors
agree on rank first. Harshit then checks Semrush volume by hand and ticks 8-12.
"""

import config
from clients import claude_cli, tavily
from stages.names import merge

EXCLUDE = ["yellowslate.com", "youtube.com", "facebook.com", "instagram.com", "quora.com", "reddit.com"]
MAX_PAGES = 8
PAGE_CHARS = 12000  # per page, keeps the prompt well inside one headless run
SHORTLIST = 15


def candidates(keyword, city=""):
    """Returns (shortlist, pages_read). Raises TavilyError / ClaudeError on failure."""
    query = f"{keyword} {city}".strip() if city and city.lower() not in keyword.lower() else keyword
    results = tavily.search(query, max_results=10, exclude=EXCLUDE)
    urls = [r["url"] for r in results][:MAX_PAGES]
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
    return merge(per_page)[:SHORTLIST], len(pages)
