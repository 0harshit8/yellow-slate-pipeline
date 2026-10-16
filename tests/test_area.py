"""The area is a fact about the school, not about the keyword.

These guard the bug that made this module necessary: a city keyword resolved to area = city,
which is a real but empty area in their CMS, so every search missed and the CMS stage created
a duplicate of a school that already existed under its real locality.

Since their Oct 11, 2026 update the module is a fallback, not a gate - their search reports
each school's own area - so what is left to test here is the text handling, the city-area
rule, and the precedence between a page, a keyword and a web lookup. The rule that an area
their CMS did not already know must be refused is GONE: they create missing areas now, and
refusing one only dropped schools for no reason.
"""

import pytest

from stages import area as area_stage
from stages.names import merge


@pytest.fixture
def no_lookup(monkeypatch):
    monkeypatch.setattr(area_stage, "lookup_area", lambda school, city: "")


# ---- clean --------------------------------------------------------------------------------

@pytest.mark.parametrize("raw, want", [
    ("Gomti Nagar", "Gomti Nagar"),
    ("Vibhuti Khand, Gomti Nagar, Lucknow 226010", "Gomti Nagar"),
    ("Gomti Nagar, Lucknow", "Gomti Nagar"),
    ("12 Mall Avenue, Hazratganj, Lucknow, Uttar Pradesh 226001", "Hazratganj"),
    ("Sector-62", "Sector 62"),
    ("Plot 5, Hazratganj, Lucknow", "Hazratganj"),
    ("Hazratganj, near the GPO", "Hazratganj"),
    ("Lucknow", ""),
    ("", ""),
])
def test_clean_keeps_only_the_locality(raw, want):
    assert area_stage.clean(raw, "Lucknow") == want


# ---- the city-named area ------------------------------------------------------------------

def test_an_area_named_after_its_city_is_refused(no_lookup):
    """area = city is their catch-all and holds no schools, so it must never be used."""
    assert area_stage.is_city_area("Lucknow", "lucknow")
    assert not area_stage.usable("Lucknow", "Lucknow")
    got, note = area_stage.resolve("Some School", "Lucknow", "Lucknow", blog_area="Lucknow")
    assert got == "", note


def test_a_city_keyword_still_resolves_from_the_page(no_lookup):
    """'best schools in Lucknow' has no area of its own. The page supplies each school's."""
    got, note = area_stage.resolve("DPS", "Lucknow", "Gomti Nagar", blog_area="Lucknow")
    assert got == "Gomti Nagar"
    assert "pages" in note


# ---- precedence ---------------------------------------------------------------------------

def test_the_page_beats_the_keyword(no_lookup):
    """A listicle for one area lists schools just outside it. Those keep their own locality."""
    got, _ = area_stage.resolve("A School", "Delhi", "Saket", blog_area="Kalkaji")
    assert got == "Saket"


def test_the_keyword_area_is_the_fallback(no_lookup):
    """An area keyword with nothing on the page still works the way it always did."""
    got, note = area_stage.resolve("A School", "Delhi", "", blog_area="Kalkaji")
    assert got == "Kalkaji"
    assert "keyword" in note


def test_a_locality_their_cms_has_not_seen_is_now_used(no_lookup):
    """The old code refused this and the school was dropped. They create the area now."""
    got, note = area_stage.resolve("A School", "Delhi", "Zzqxville", blog_area="")
    assert got == "Zzqxville"
    assert "pages" in note


def test_an_unknown_page_locality_does_not_fall_back_to_the_keyword(no_lookup):
    """The page naming a locality is evidence the school is not in the keyword's area.

    Filing it under Kalkaji because the keyword said so would put a school the page placed
    somewhere else into the wrong part of a live CMS.
    """
    got, _ = area_stage.resolve("A School", "Delhi", "Greater Kailash II", blog_area="Kalkaji")
    assert got == "Greater Kailash II"


def test_the_lookup_is_the_last_resort(monkeypatch):
    monkeypatch.setattr(area_stage, "lookup_area", lambda school, city: "Gomti Nagar")
    got, note = area_stage.resolve("DPS", "Lucknow", "", blog_area="Lucknow")
    assert got == "Gomti Nagar"
    assert "lookup" in note


def test_nothing_anywhere_is_unresolved(no_lookup):
    got, note = area_stage.resolve("DPS", "Lucknow", "", blog_area="Lucknow")
    assert got == ""
    assert "no area" in note


# ---- among: the candidates their CMS offered for a shared name -----------------------------

def test_among_restricts_the_answer_to_their_candidate_areas(no_lookup):
    """Their candidate list is every place a school of that name exists.

    An answer outside it would create a duplicate instead of matching one of those rows, so
    a page locality that is not among them is not good enough to act on.
    """
    got, note = area_stage.resolve("Kidzee", "Delhi", "Saket", among=["Dwarka", "Kalkaji"])
    assert got == ""
    assert "Dwarka" in note and "Kalkaji" in note


def test_among_accepts_a_page_locality_that_is_one_of_them(no_lookup):
    got, note = area_stage.resolve("Kidzee", "Delhi", "Kalkaji, New Delhi",
                                   among=["Dwarka", "Kalkaji"])
    assert got == "Kalkaji"
    assert "pages" in note


def test_among_matches_regardless_of_case(no_lookup):
    got, _ = area_stage.resolve("Kidzee", "Delhi", "kalkaji", among=["Kalkaji"])
    assert got == "kalkaji"


def test_among_matches_their_prefixed_area_spelling(no_lookup):
    """Their CMS files some localities behind a prefix: "South Campus,South Moti Bagh".

    The pages give the locality on its own, and clean() cuts their string down to the same
    locality, so the two do match - but only after cleaning. What goes back is THEIR string,
    because their CMS matches an area on the exact characters and the plain locality would
    be ignored as an area they do not have.
    """
    got, note = area_stage.resolve("Springdales School", "Delhi", "South Moti Bagh",
                                   among=["Dhaula Kuan", "South Campus,South Moti Bagh"])
    assert got == "South Campus,South Moti Bagh"
    assert "pages" in note


def test_among_matches_an_abbreviated_area(no_lookup):
    """Their CMS holds "Mathura Rd"; every competitor page writes "Mathura Road"."""
    got, _ = area_stage.resolve("Delhi Public School", "Delhi", "Mathura Road",
                                among=["Vasant Kunj", "Mathura Rd"])
    assert got == "Mathura Rd"


def test_among_matches_across_punctuation(no_lookup):
    """"R.K. Puram" and "R. K. Puram" are one place written two ways."""
    got, _ = area_stage.resolve("Delhi Public School", "Delhi", "R.K. Puram",
                                among=["Dwarka", "R. K. Puram"])
    assert got == "R. K. Puram"


def test_two_numbered_blocks_are_not_the_same_locality(no_lookup):
    """Greater Kailash and Greater Kailash 1 are different places, so the digit must count."""
    got, _ = area_stage.resolve("Bluebells", "Delhi", "Greater Kailash 2",
                                among=["Greater Kailash", "Greater Kailash 1"])
    assert got == ""


def test_a_prefixed_candidate_still_has_to_be_the_same_locality(no_lookup):
    """Matching on the cleaned form must not become a way in for an unrelated area."""
    got, _ = area_stage.resolve("Kidzee", "Delhi", "Saket",
                                among=["South Campus,South Moti Bagh"])
    assert got == ""


# ---- merge carries the locality -------------------------------------------------------------

def test_merge_carries_the_locality_onto_the_school():
    out = merge({
        "a": [{"name": "DPS Gomti Nagar", "area": "Gomti Nagar"}],
        "b": [{"name": "Delhi Public School Gomti Nagar", "area": ""}],
        "c": [{"name": "Delhi Public School, Gomti Nagar", "area": "Gomti Nagar"}],
    }, city="Lucknow")
    assert out[0]["count"] == 3
    assert out[0]["area"] == "Gomti Nagar"


def test_merge_leaves_an_unknown_locality_empty():
    out = merge({"a": [{"name": "A School", "area": ""}], "b": [{"name": "A School"}]})
    assert out[0]["area"] == ""


def test_merge_joins_the_same_school_across_locality_spellings():
    """"La Martiniere College, Hazratganj" and "La Martiniere College, Lucknow" are one school."""
    out = merge({
        "a": [{"name": "La Martiniere College, Hazratganj", "area": "Hazratganj"}],
        "b": [{"name": "La Martiniere College, Lucknow", "area": ""}],
        "c": [{"name": "La Martiniere College", "area": "Hazratganj"}],
    }, city="Lucknow")
    assert len(out) == 1
    assert out[0]["count"] == 3
    assert out[0]["area"] == "Hazratganj"


def test_merge_keeps_two_campuses_of_one_chain_apart():
    """Separate campuses are separate CMS rows. Discounting the locality must not fold them."""
    out = merge({
        "a": [{"name": "CMS City Montessori School Campus 1 Gomti Nagar", "area": "Gomti Nagar"}],
        "b": [{"name": "CMS City Montessori School Kanpur Road Campus", "area": "Kanpur Road"}],
    }, city="Lucknow")
    assert len(out) == 2
    assert {s["area"] for s in out} == {"Gomti Nagar", "Kanpur Road"}


def test_merge_still_accepts_bare_names():
    """The old shape must keep working, so an older pick.json can still be replayed."""
    out = merge({"a": ["DAV Public School"], "b": ["DAV Public School"]})
    assert out[0]["name"] == "DAV Public School"
    assert out[0]["count"] == 2
    assert out[0]["area"] == ""
