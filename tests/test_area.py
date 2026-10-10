"""The area is a fact about the school, not about the keyword.

These guard the bug that made this module necessary: a city keyword resolved to area = city,
which is a real but empty area in their CMS, so every search missed and the CMS stage created
a duplicate of a school that already existed under its real locality.
"""

import pytest

from stages import area as area_stage
from stages.names import merge


@pytest.fixture(autouse=True)
def no_cache():
    area_stage._known.clear()
    yield
    area_stage._known.clear()


@pytest.fixture
def cms_knows(monkeypatch):
    """Pretend their CMS knows this set of (city, area) pairs, and nothing else."""
    def install(pairs):
        allowed = {(c.lower(), a.lower()) for c, a in pairs}
        monkeypatch.setattr(area_stage, "known",
                            lambda city, area: (city.strip().lower(), area.strip().lower()) in allowed)
    return install


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

def test_an_area_named_after_its_city_is_refused(cms_knows, no_lookup):
    """area = city passes their 404 check but holds no schools, so it must never be used."""
    cms_knows([("Lucknow", "Lucknow"), ("Lucknow", "Gomti Nagar")])
    assert area_stage.is_city_area("Lucknow", "lucknow")
    got, note = area_stage.resolve("Some School", "Lucknow", "Lucknow", blog_area="Lucknow")
    assert got == "", note


def test_a_city_keyword_still_resolves_from_the_page(cms_knows, no_lookup):
    """'best schools in Lucknow' has no area of its own. The page supplies each school's."""
    cms_knows([("Lucknow", "Gomti Nagar")])
    got, note = area_stage.resolve("DPS", "Lucknow", "Gomti Nagar", blog_area="Lucknow")
    assert got == "Gomti Nagar"
    assert "pages" in note


# ---- precedence ---------------------------------------------------------------------------

def test_the_page_beats_the_keyword(cms_knows, no_lookup):
    """A listicle for one area lists schools just outside it. Those keep their own locality."""
    cms_knows([("Delhi", "Kalkaji"), ("Delhi", "Saket")])
    got, _ = area_stage.resolve("A School", "Delhi", "Saket", blog_area="Kalkaji")
    assert got == "Saket"


def test_the_keyword_area_is_the_fallback(cms_knows, no_lookup):
    """An area keyword with nothing on the page still works the way it always did."""
    cms_knows([("Delhi", "Kalkaji")])
    got, note = area_stage.resolve("A School", "Delhi", "", blog_area="Kalkaji")
    assert got == "Kalkaji"
    assert "keyword" in note


def test_an_area_their_cms_does_not_know_is_not_used(cms_knows, no_lookup):
    cms_knows([("Delhi", "Kalkaji")])
    got, note = area_stage.resolve("A School", "Delhi", "Zzqxville", blog_area="")
    assert got == ""
    assert "Zzqxville" in note


def test_an_unknown_page_locality_does_not_fall_back_to_the_keyword(cms_knows, no_lookup):
    """The page naming a locality is evidence the school is not in the keyword's area.

    Filing it under Kalkaji because Kalkaji happens to be a known area would put a school
    the page placed somewhere else into the wrong part of a live CMS.
    """
    cms_knows([("Delhi", "Kalkaji")])
    got, note = area_stage.resolve("A School", "Delhi", "Greater Kailash II", blog_area="Kalkaji")
    assert got == ""
    assert "Greater Kailash II" in note


def test_the_lookup_is_the_last_resort(cms_knows, monkeypatch):
    cms_knows([("Lucknow", "Gomti Nagar")])
    monkeypatch.setattr(area_stage, "lookup_area", lambda school, city: "Gomti Nagar")
    got, note = area_stage.resolve("DPS", "Lucknow", "", blog_area="Lucknow")
    assert got == "Gomti Nagar"
    assert "lookup" in note


def test_a_lookup_answer_their_cms_rejects_is_still_refused(cms_knows, monkeypatch):
    cms_knows([("Lucknow", "Gomti Nagar")])
    monkeypatch.setattr(area_stage, "lookup_area", lambda school, city: "Nowhere Colony")
    got, note = area_stage.resolve("DPS", "Lucknow", "", blog_area="Lucknow")
    assert got == ""
    assert "Nowhere Colony" in note


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
