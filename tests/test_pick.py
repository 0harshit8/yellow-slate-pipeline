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
    assert included == [[d] for d in pick.searched_domains()], (
        "one search per domain, so no two ever share a pool of slots. The rated directories "
        "are searched the same way and after the preferred ones"
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


# The deterministic rating read. Guards the bug that left every Kalkaji candidate at
# reviews = 0 while the pages in the prompt printed a vote count for most of them.
#
# Measured on Kalkaji, Oct 15 2026. Justdial is the only domain RATED names, and both of
# its Kalkaji pages failed at BOTH depths: "Request timed out" at basic and "Failed to
# fetch url" at advanced, twice. Pune's two list pages failed the same way and Hauz Khas
# returned no Justdial hits at all, so the advanced retry is not a general rescue - only
# Kolar's bare /Kolar/Schools/ page happened to be fetchable.
#
# Edustoke is the directory that actually carries the signal: its Kalkaji page extracts in
# full at 62,172 characters and prints "4.0(9 votes)" next to each school. But PAGE_CHARS
# cuts that page to its first 12,000 characters, which holds 6 of its 25 vote counts, so 19
# were thrown away before the model ever saw them. Reading the counts off the FULL body with
# a regex costs nothing, cannot be truncated and does not depend on the model noticing.
EDUSTOKE_ROW = (
    "![](https://storage.googleapis.com/cdn-edustoke/thumb.webp)  "
    "[KALKA PUBLIC SCHOOL](/delhi/kalka-public-school-alaknanda)  "
    "Alaknanda, Delhi  4.0(9 votes)  School typeDay School"
)
EZYSCHOOLING_ROW = (
    "[Sri Satya Sai Vidya Vihar School](/school/sri-satya-sai-vidya-vihar-school-kalkaji)  "
    "[5.0  1 Review](/school/sri-satya-sai-vidya-vihar-school-kalkaji)"
)
UNRATED_ROW = (
    "[RAM KRISHNA SARASWATI VIDYA NIKETAN](/delhi/ram-krishna-saraswati-vidya-niketan)  "
    "NEHRU ENCLAVE, Delhi  0.0(0 votes)  School typeDay School"
)


def test_a_vote_count_is_read_off_the_page_without_the_model():
    assert pick.page_ratings(EDUSTOKE_ROW) == {"kalka public school": 9}


def test_a_review_count_in_ezyschoolings_shape_is_read_too():
    assert pick.page_ratings(EZYSCHOOLING_ROW) == {"sri satya sai vidya vihar school": 1}


def test_a_school_with_no_votes_is_not_credited_with_any():
    assert pick.page_ratings(UNRATED_ROW) == {}, (
        "0.0(0 votes) means nobody rated it, not that the count is unknown"
    )


def test_a_rating_past_the_prompt_window_is_still_read():
    body = ("filler. " * 4000) + EDUSTOKE_ROW
    assert len(body) > pick.PAGE_CHARS, "this body must outrun the prompt window"
    assert pick.page_ratings(body) == {"kalka public school": 9}, (
        "19 of edustoke's 25 Kalkaji vote counts sat past PAGE_CHARS; the regex reads the "
        "whole body, so truncation cannot hide them"
    )


def test_the_page_count_lifts_a_school_the_model_recorded_as_unrated(monkeypatch):
    page = "https://www.edustoke.com/delhi/cbse-schools-in-kalkaji"
    monkeypatch.setattr(pick.tavily, "search", lambda q, **k: [{"url": page}])
    monkeypatch.setattr(pick.tavily, "extract",
                        lambda urls, depth="basic": {u: EDUSTOKE_ROW for u in urls})
    monkeypatch.setattr(config, "read_prompt", lambda name: "{keyword} {pages}")
    monkeypatch.setattr(claude_cli, "run_json", lambda *a, **k: {"pages": [
        {"url": page, "schools": [{"name": "Kalka Public School", "area": "Alaknanda",
                                   "reviews": 0}]},
    ]})

    shortlist, _ = pick.candidates("best schools in Kalkaji", city="Delhi")
    assert [s["reviews"] for s in shortlist] == [9], (
        "the model read this page and returned 0; the page itself prints 9 votes"
    )


def test_the_model_still_wins_when_it_found_the_larger_count(monkeypatch):
    page = "https://www.edustoke.com/delhi/cbse-schools-in-kalkaji"
    monkeypatch.setattr(pick.tavily, "search", lambda q, **k: [{"url": page}])
    monkeypatch.setattr(pick.tavily, "extract",
                        lambda urls, depth="basic": {u: EDUSTOKE_ROW for u in urls})
    monkeypatch.setattr(config, "read_prompt", lambda name: "{keyword} {pages}")
    monkeypatch.setattr(claude_cli, "run_json", lambda *a, **k: {"pages": [
        {"url": page, "schools": [{"name": "Kalka Public School", "area": "Alaknanda",
                                   "reviews": 42}]},
    ]})

    shortlist, _ = pick.candidates("best schools in Kalkaji", city="Delhi")
    assert [s["reviews"] for s in shortlist] == [42], (
        "the regex is a floor under the model's number, never a cap on it"
    )


# The list-shaped slot rule. Guards the same careers360 bug the per-domain search fixed for
# Kolar but not for Kalkaji.
#
# Measured on Kalkaji, Oct 15 2026: include=["school.careers360.com"] with max_results=5
# returned school-of-excellence-kalkaji-new-delhi and
# government-co-educational-senior-secondary-school-kalkaji-new-delhi FIRST, then
# schools-in-delhi and hindi-medium-schools-in-delhi, then an article. Keeping the first two
# spends both slots on single-school pages, which carry one locality each and no list - so
# the city list this block exists for never arrived, exactly as it did not for Kolar.
C360_KALKAJI = [
    "https://school.careers360.com/schools/school-of-excellence-kalkaji-new-delhi",
    "https://school.careers360.com/schools/government-co-educational-senior-secondary-school-kalkaji-new-delhi",
    "https://school.careers360.com/schools/schools-in-delhi",
    "https://school.careers360.com/schools/hindi-medium-schools-in-delhi",
    "https://school.careers360.com/articles/nursery-admission-in-delhi",
]


@pytest.fixture
def kalkaji_tavily(monkeypatch):
    """Answers the careers360 search the way Tavily answered it for Kalkaji."""
    def search(query, max_results=10, exclude=None, include=None):
        if include == ["school.careers360.com"]:
            return [{"url": u} for u in C360_KALKAJI[:max_results]]
        if include:
            return []
        return [{"url": RANKING}]

    monkeypatch.setattr(pick.tavily, "search", search)
    monkeypatch.setattr(pick.tavily, "extract",
                        lambda urls, depth="basic": {u: f"body of {u}" for u in urls})
    monkeypatch.setattr(config, "read_prompt", lambda name: "{keyword} {pages}")
    monkeypatch.setattr(claude_cli, "run_json", lambda *a, **k: {"pages": []})


def test_a_city_list_takes_the_slot_a_single_school_page_ranked_above(kalkaji_tavily):
    urls = pick._urls("best schools in Kalkaji Delhi")
    kept = [u for u in urls if "careers360" in u]
    assert "https://school.careers360.com/schools/schools-in-delhi" in kept, (
        "careers360 is preferred for its city list; two single-school pages ranked above "
        "it and took both slots"
    )


def test_a_single_school_page_still_fills_a_slot_when_no_list_ranks(monkeypatch):
    singles = C360_KALKAJI[:2]

    def search(query, max_results=10, exclude=None, include=None):
        if include == ["school.careers360.com"]:
            return [{"url": u} for u in singles]
        if include:
            return []
        return [{"url": RANKING}]

    monkeypatch.setattr(pick.tavily, "search", search)
    urls = pick._urls("best schools in Kalkaji Delhi")
    assert singles[0] in urls, (
        "a single-school page is worth less than a list, not worth nothing"
    )


# Link text that is a button, not a school. Measured on the real pages, Oct 15 2026: reading
# the nearest link above each rating credited "View School" with 7 ratings on edustoke, and on
# ezyschooling the "Session: 2027-2028" link sits between the school's name and its rating, so
# "Session 2027 2028" collected the count and 4 of the page's 5 ratings were lost.
EDUSTOKE_BUTTON = (
    "[KALKA PUBLIC SCHOOL](/delhi/kalka-public-school-alaknanda)  Alaknanda, Delhi  "
    "[View School](/delhi/kalka-public-school-alaknanda)  8.6k  1.32 km  4.09 votes"
)
EZYSCHOOLING_ROW_FULL = (
    "[Sri Satya Sai Vidya Vihar School](/school/sri-satya-sai-vidya-vihar-school-kalkaji)  "
    "[Session:  2027-2028](/school/sri-satya-sai-vidya-vihar-school-kalkaji)  "
    "[5.0  1 Review](/school/sri-satya-sai-vidya-vihar-school-kalkaji)"
)


def test_a_view_school_button_is_not_credited_with_the_rating():
    assert pick.page_ratings(EDUSTOKE_BUTTON) == {"kalka public school": 9}


def test_a_session_label_between_the_name_and_the_rating_is_skipped():
    assert pick.page_ratings(EZYSCHOOLING_ROW_FULL) == {
        "sri satya sai vidya vihar school": 1
    }


# Ezyschooling stacks two field labels between a school's name and its rating. Measured
# Oct 15 2026: with only the button stoplist in place, its Kalkaji page yielded
# "classes nursery 12 class", "classes nursery 5 class" and "classes 1 12 class" instead of
# three school names. Every such label carries a colon, and a school's name never does.
EZYSCHOOLING_LABELLED = (
    "[Sri Satya Sai Vidya Vihar School](/school/sri-satya-sai-vidya-vihar-school-kalkaji)  "
    "[Classes:  Nursery - Class 12](/school/sri-satya-sai-vidya-vihar-school-kalkaji)  "
    "[Session:  2027-2028](/school/sri-satya-sai-vidya-vihar-school-kalkaji)  "
    "[5.0  1 Review](/school/sri-satya-sai-vidya-vihar-school-kalkaji)"
)


def test_a_field_label_is_not_mistaken_for_the_school_name():
    assert pick.page_ratings(EZYSCHOOLING_LABELLED) == {
        "sri satya sai vidya vihar school": 1
    }


# The shape ezyschooling really prints, read off its Kalkaji page Oct 15 2026. Between a
# school's name and its rating sit four links: the locality as an h4, a monthly fee in
# rupees, and two colon labels. The name itself is an h3 inside the link text. Taking the
# nearest link above the rating gave "monthlyfees 2 86 k 3 17 k"; rejecting that alone would
# have taken the locality line next and credited "kalkaji south east delhi" with the rating.
# A wrong name is worse than none, so every one of those four shapes has to be ruled out.
EZYSCHOOLING_REAL = (
'[### Sri Satya Sai Vidya Vihar School](/school/sri-satya-sai-vidya-vihar-school-kalkaji-south-east-delhi)\n\n[#### Kalkaji, South East Delhi](/school/sri-satya-sai-vidya-vihar-school-kalkaji-south-east-delhi)\n\n[MonthlyFees\n\n₹ 2.86 K - 3.17 K](/school/sri-satya-sai-vidya-vihar-school-kalkaji-south-east-delhi)\n\n[Board:\n\nCBSE](/school/sri-satya-sai-vidya-vihar-school-kalkaji-south-east-delhi)\n\n[Classes:\n\n1 - 12 Class](/school/sri-satya-sai-vidya-vihar-school-kalkaji-south-east-delhi)\n\n[Session:\n\n2027-2028](/school/sri-satya-sai-vidya-vihar-school-kalkaji-south-east-delhi)\n\n[5.0\n\n1 Review](/school/sri-satya-sai-vidya-vihar-school-kalkaji-south-east-delhi)'
)


def test_the_school_name_is_found_under_ezyschoolings_stack_of_labels():
    assert pick.page_ratings(EZYSCHOOLING_REAL) == {
        "sri satya sai vidya vihar school": 1
    }


def test_a_locality_subheading_is_never_credited_with_the_rating():
    assert "kalkaji south east delhi" not in pick.page_ratings(EZYSCHOOLING_REAL)


# Not every fee line carries a currency symbol. Measured on ezyschooling's Kalkaji page,
# Oct 15 2026: a school whose fee is unpublished prints "MonthlyFees NA", which has no rupee
# sign, no colon and no heading mark, so it slipped through and collected 3 ratings.
EZYSCHOOLING_FEE_NA = (
    "[### Oxford Public School](/school/oxford-public-school-kalkaji)\n\n"
    "[MonthlyFees\n\nNA](/school/oxford-public-school-kalkaji)\n\n"
    "[4.0\n\n3 Reviews](/school/oxford-public-school-kalkaji)"
)


def test_a_fee_line_without_a_currency_symbol_is_still_not_a_school():
    assert pick.page_ratings(EZYSCHOOLING_FEE_NA) == {"oxford public school": 3}
