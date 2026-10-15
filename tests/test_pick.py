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
