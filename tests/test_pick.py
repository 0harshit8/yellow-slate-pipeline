"""The picker's page-reading step. Guards the bug that emptied the parent review graphs.

Measured on Kolar, Oct 15 2026: Justdial was found by search and ranked first in the URL
list, but Tavily's basic extract answered "Request timed out" for it and clients/tavily.py
drops a failed URL silently. So the one page in the run that printed a rating count per
school never reached the extractor, every candidate arrived with reviews = 0, and nine of
ten review graphs in the post had nothing real to draw. The same page at advanced depth
came back in 6687 characters carrying ten schools with their ratings and localities.
"""

import pytest

import config
from clients import claude_cli, tavily
from stages import pick

RANKING = "https://example.com/best-schools"
SLOW = "https://www.justdial.com/Kolar/Schools/nct-10422444"


@pytest.fixture
def fake_tavily(monkeypatch):
    """Stubs search and extract. SLOW only yields a body at advanced depth, like Justdial."""
    calls = []

    def search(query, max_results=10, exclude=None, include=None):
        if include:
            return [{"url": SLOW}]
        return [{"url": RANKING}]

    def extract(urls, depth="basic"):
        calls.append((tuple(urls), depth))
        out = {}
        for u in urls:
            if u == SLOW and depth != "advanced":
                continue  # timed out: the client leaves a failed URL out
            out[u] = f"body of {u}"
        return out

    monkeypatch.setattr(pick.tavily, "search", search)
    monkeypatch.setattr(pick.tavily, "extract", extract)
    monkeypatch.setattr(config, "read_prompt", lambda name: "{keyword} {pages}")
    monkeypatch.setattr(claude_cli, "run_json", lambda *a, **k: {"pages": []})
    return calls


def test_a_page_the_basic_extract_lost_is_retried_at_advanced_depth(fake_tavily):
    pick.candidates("best schools in Kolar", city="Kolar")
    depths = [depth for _, depth in fake_tavily]
    assert "advanced" in depths, "a timed-out page must be retried at advanced depth"
    retried = [urls for urls, depth in fake_tavily if depth == "advanced"]
    assert retried == [(SLOW,)], "only the pages that came back empty should be retried"


def test_the_recovered_page_reaches_the_extractor(fake_tavily):
    _, pages_read = pick.candidates("best schools in Kolar", city="Kolar")
    assert pages_read == 2, "the recovered page must be counted and sent to the prompt"


def test_no_retry_when_the_basic_extract_got_everything(monkeypatch):
    calls = []
    monkeypatch.setattr(pick.tavily, "search", lambda q, **k: [{"url": RANKING}])

    def extract(urls, depth="basic"):
        calls.append(depth)
        return {u: f"body of {u}" for u in urls}

    monkeypatch.setattr(pick.tavily, "extract", extract)
    monkeypatch.setattr(config, "read_prompt", lambda name: "{keyword} {pages}")
    monkeypatch.setattr(claude_cli, "run_json", lambda *a, **k: {"pages": []})

    pick.candidates("best schools in Kolar", city="Kolar")
    assert calls == ["basic"], "a clean run must not pay for an advanced extract"


def test_extract_passes_the_depth_through_to_the_api(monkeypatch):
    sent = {}

    def _call(path, payload):
        sent.update(payload)
        return {"results": []}

    monkeypatch.setattr(tavily, "_call", _call)
    tavily.extract(["https://example.com"], depth="advanced")
    assert sent["extract_depth"] == "advanced"


# The preferred-directory search. Guards the bug that spent careers360's slots on single
# school pages, which carry one locality each and no list at all.
#
# Measured on Kolar, Oct 15 2026. One search with include=PREFERRED (both domains) and
# max_results=3 returned justdial's Kolar page plus two careers360 SCHOOL pages
# (christ-international-school-alambady-kolar, gnana-jyothi-school-mulbagal-kolar), so two
# of the three shared slots went to single schools. The same day,
# include=["school.careers360.com"] alone with max_results=5 returned five "schools in
# Kolar" city lists (kseeb-, cbse-, karnataka-board-pue-, central-government-,
# day-cum-boarding-). Tavily ranks freely inside the included domains, so one shared pool
# lets one domain take the other's slots.
#
# Also measured that day: that same single-domain search with max_results=3 returned 0 hits
# while max_results=5 returned 5. A small max_results is not the top N of a larger set, so
# the stub below returns nothing at all to a search that asks for too few.

C360_LISTS = [
    "https://school.careers360.com/schools/kseeb-schools-in-kolar",
    "https://school.careers360.com/schools/cbse-schools-in-kolar",
    "https://school.careers360.com/schools/karnataka-board-pue-schools-in-kolar",
    "https://school.careers360.com/schools/central-government-schools-in-kolar",
    "https://school.careers360.com/schools/day-cum-boarding-schools-in-kolar",
]
C360_SCHOOLS = [
    "https://school.careers360.com/schools/christ-international-school-alambady-kolar",
    "https://school.careers360.com/schools/gnana-jyothi-school-mulbagal-kolar",
]
C360_MIN_RESULTS = 5  # asking for fewer than this came back empty, measured above


@pytest.fixture
def measured_tavily(monkeypatch):
    """Answers a preferred search the way Tavily answered it for Kolar, per include set."""
    searches = []

    def search(query, max_results=10, exclude=None, include=None):
        searches.append({"max_results": max_results, "include": include})
        if not include:
            return [{"url": RANKING}]
        domains = tuple(sorted(include))
        if domains == tuple(sorted(pick.PREFERRED)):
            pool = [SLOW] + C360_SCHOOLS  # the shared pool, as measured
        elif domains == ("school.careers360.com",):
            pool = C360_LISTS if max_results >= C360_MIN_RESULTS else []
        elif domains == ("justdial.com",):
            pool = [SLOW]
        else:
            pool = []
        return [{"url": u} for u in pool[:max_results]]

    monkeypatch.setattr(pick.tavily, "search", search)
    monkeypatch.setattr(pick.tavily, "extract",
                        lambda urls, depth="basic": {u: f"body of {u}" for u in urls})
    monkeypatch.setattr(config, "read_prompt", lambda name: "{keyword} {pages}")
    monkeypatch.setattr(claude_cli, "run_json", lambda *a, **k: {"pages": []})
    return searches


def test_a_careers360_city_list_wins_its_own_slot(measured_tavily):
    urls = pick._urls("best schools in Kolar")
    assert [u for u in urls if u in C360_LISTS], (
        "the city list is the whole reason careers360 is preferred; a shared pool spends "
        "its slots on single school pages instead"
    )


def test_justdial_is_not_crowded_out_by_the_other_domain(measured_tavily):
    urls = pick._urls("best schools in Kolar")
    assert SLOW in urls, "justdial is the only rated source; it needs a slot of its own"


def test_each_preferred_domain_is_searched_on_its_own(measured_tavily):
    pick._urls("best schools in Kolar")
    included = [s["include"] for s in measured_tavily if s["include"]]
    assert included == [[d] for d in pick.PREFERRED], (
        "one search per preferred domain, so the two never share a pool of slots"
    )


def test_the_preferred_pages_leave_room_for_the_ranking_pages(measured_tavily):
    urls = pick._urls("best schools in Kolar")
    assert len(urls) <= pick.MAX_PAGES, "the page budget is MAX_PAGES in total"
    assert RANKING in urls, "the pages that actually rank must still be read"


def test_one_dead_preferred_domain_does_not_lose_the_other(monkeypatch):
    def search(query, max_results=10, exclude=None, include=None):
        if include and "school.careers360.com" in include:
            raise tavily.TavilyError("careers360 is down")
        if include:
            return [{"url": SLOW}]
        return [{"url": RANKING}]

    monkeypatch.setattr(pick.tavily, "search", search)
    urls = pick._urls("best schools in Kolar")
    assert SLOW in urls, "a failure in one preferred domain must not lose the other"
    assert RANKING in urls, "nor stop the ranking pages"
