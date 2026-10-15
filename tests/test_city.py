"""Their CMS has no rule about city names, so we ask it rather than guess.

Measured against the live API on Oct 11, 2026: it uses the modern name 14 times out of 32
old/new pairs and the old name 10 times. The alias table these tests replace assumed modern
always wins, and so rewrote "Mysore" to "Mysuru" and "Vizag" to "Visakhapatnam", both of
which their API 404s on. That is the regression guarded here: a normaliser that turns a
WORKING spelling into a broken one is worse than no normaliser at all.
"""

import pytest

from clients.cms_fake import FakeCMS
from stages import city as city_stage


@pytest.fixture
def cms(tmp_path):
    """Their CMS as measured: 'Mysore' not 'Mysuru', 'Bengaluru' not 'Bangalore', no Thane."""
    return FakeCMS(path=str(tmp_path / "fake.json"),
                   cities=["Delhi", "Mysore", "Bengaluru", "Vizag", "Allahabad", "Trichy",
                           "Calicut", "Pune", "Gurugram"])


# ---- variants -----------------------------------------------------------------------------

def test_the_spelling_as_given_is_always_tried_first():
    assert city_stage.variants("Bangalore")[0] == "Bangalore"


def test_a_trailing_state_is_dropped():
    assert city_stage.variants("Pune, Maharashtra") == ["Pune, Maharashtra", "Pune", "Poona"]


def test_the_other_names_for_the_place_are_offered():
    got = {v.lower() for v in city_stage.variants("Vizag")}
    assert {"vizag", "visakhapatnam"} <= got


def test_variants_never_repeat_a_spelling():
    got = city_stage.variants("Delhi")
    assert len(got) == len({v.lower() for v in got})


def test_an_empty_city_has_no_variants():
    assert city_stage.variants("") == []
    assert city_stage.variants("   ") == []


# ---- resolve, both directions -------------------------------------------------------------

def test_a_spelling_they_already_have_is_left_alone(cms):
    """The regression. 'Mysore' works, so nothing may rewrite it to the official 'Mysuru'."""
    theirs, note = city_stage.resolve(cms, "Mysore")
    assert theirs == "Mysore"
    assert note == ""


def test_the_official_name_is_corrected_to_their_old_one(cms):
    theirs, note = city_stage.resolve(cms, "Mysuru")
    assert theirs == "Mysore"
    assert "Mysore" in note


def test_the_old_name_is_corrected_to_their_official_one(cms):
    """And the other direction, which is why a one-way table cannot work."""
    theirs, note = city_stage.resolve(cms, "Bangalore")
    assert theirs == "Bengaluru"
    assert "Bengaluru" in note


@pytest.mark.parametrize("given, want", [
    ("Visakhapatnam", "Vizag"),
    ("Prayagraj", "Allahabad"),
    ("Tiruchirappalli", "Trichy"),
    ("Kozhikode", "Calicut"),
    ("Gurgaon", "Gurugram"),
    ("New Delhi", "Delhi"),
    ("Pune, Maharashtra", "Pune"),
])
def test_measured_corrections(cms, given, want):
    theirs, _ = city_stage.resolve(cms, given)
    assert theirs == want


def test_case_and_spacing_do_not_count_as_a_rename(cms):
    """Their city field is case-insensitive and trims, so this is not worth reporting."""
    theirs, note = city_stage.resolve(cms, "  delhi ")
    assert theirs.lower() == "delhi"
    assert note == ""


def test_a_city_they_do_not_have_is_reported_not_invented(cms):
    theirs, note = city_stage.resolve(cms, "Thane")
    assert theirs == ""
    assert "Thane" in note
    assert "Yellow Slate" in note


def test_a_city_missing_under_every_name_lists_what_was_tried(cms):
    theirs, note = city_stage.resolve(cms, "Pondicherry")
    assert theirs == ""
    assert "Puducherry" in note      # says both were tried, so it is not retried by hand


def test_no_city_given(cms):
    theirs, note = city_stage.resolve(cms, "")
    assert theirs == ""
    assert note == "no city given"
