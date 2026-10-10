import pytest

from clients.cms_base import CMSError
from clients.cms_fake import FakeCMS
from stages.cms import ensure_school
from stages.names import cms_name, merge, normalize, school_email


def test_normalize_expands_short_forms_once():
    assert normalize("DPS R.K. Puram") == "delhi public school r k puram"
    assert normalize("Delhi Public School") == "delhi public school"
    assert normalize("DAV Public School") == "dav public school"


def test_cms_name_is_the_plain_name_without_the_area():
    """Their API appends the area to the slug, and their existing rows carry plain names."""
    assert cms_name("DPS", "Kalkaji") == "Delhi Public School"
    assert cms_name("Bal Bharati Public School Kalkaji", "Kalkaji") == "Bal Bharati Public School"
    assert cms_name("The British School", "Chanakyapuri") == "The British School"
    assert cms_name("Kidzee Kalkaji", "Kalkaji") == "Kidzee"


def test_cms_name_never_returns_empty():
    """A school named only after its area must not be stripped to nothing."""
    assert cms_name("Kalkaji", "Kalkaji") == "Kalkaji"


def test_email_follows_their_domain():
    assert school_email("Example School", "Delhi", "Kalkaji") == \
        "delhi-example-school-kalkaji@schools.yellowslate.com"


def test_email_is_unique_per_area():
    """Same school name, two areas, two different mailboxes."""
    assert school_email("Deepalaya School", "Delhi", "Kalkaji") != \
        school_email("Deepalaya School", "Delhi", "Sarita Vihar")


def test_email_stays_inside_the_64_character_local_part():
    long_name = "Government Senior Secondary Special School Co-Ed For The Hearing Impaired"
    email = school_email(long_name, "Delhi", "Kalkaji")
    local = email.split("@")[0]
    assert len(local) <= 64, local
    assert email.endswith("@schools.yellowslate.com")
    # a different long name must not collide once both are truncated
    assert school_email(long_name + " Number Two", "Delhi", "Kalkaji") != email


def test_merge_counts_pages_not_mentions():
    out = merge({
        "a": ["DPS Kalkaji", "Bal Bharati Public School"],
        "b": ["Delhi Public School Kalkaji", "Bal Bharti Public School"],
        "c": ["Delhi Public School, Kalkaji", "Delhi Public School Kalkaji"],
    })
    top = {s["name"]: s["count"] for s in out}
    assert top["Delhi Public School, Kalkaji"] == 3 or top.get("Delhi Public School Kalkaji") == 3
    assert out[0]["count"] == 3
    assert any(s["count"] == 2 and "Bal" in s["name"] for s in out)


@pytest.fixture
def cms(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    return FakeCMS(path=str(tmp_path / "fake.json"))


def test_create_then_rerun_reuses(cms):
    first = ensure_school(cms, "DPS", "Delhi", "Kalkaji")
    again = ensure_school(cms, "Delhi Public School", "Delhi", "Kalkaji")
    assert first["created"] and not again["created"]
    assert first["id"] == again["id"]
    # plain name in, so the area appears once in the slug, not twice
    assert first["slug"] == "delhi/delhi-public-school-kalkaji"
    assert len(cms.schools) == 1
    assert cms.schools[0]["verified"] is False and cms.schools[0]["claimed"] is False


def test_same_name_other_area_is_new_school(cms):
    a = ensure_school(cms, "Delhi Public School", "Delhi", "Kalkaji")
    b = ensure_school(cms, "Delhi Public School", "Delhi", "Saket")
    assert a["id"] != b["id"]


def test_duplicate_email_rejected(cms):
    cms.create_school("X School Kalkaji", "Delhi", "Kalkaji", "x@gmail.com")
    with pytest.raises(CMSError):
        cms.create_school("X School Kalkaji 2", "Delhi", "Kalkaji", "x@gmail.com")


def test_blog_slug():
    from stages.names import blog_slug
    assert blog_slug("schools in Hauz Khas", "Delhi") == "best-schools-in-hauz-khas-delhi"
    assert blog_slug("Best Schools in Kalkaji", "Delhi") == "best-schools-in-kalkaji-delhi"
    assert blog_slug("best schools in hauz khas delhi", "Delhi") == "best-schools-in-hauz-khas-delhi"


def test_shared_filler_words_dont_match(cms):
    """Regression: DAV was matched to Kalka because 'Public School Kalkaji' is shared."""
    kalka = ensure_school(cms, "Kalka Public School", "Delhi", "Kalkaji")
    dav = ensure_school(cms, "DAV Public School", "Delhi", "Kalkaji")
    assert dav["created"] and dav["id"] != kalka["id"]


def test_spelling_variants_still_match(cms):
    a = ensure_school(cms, "Guru Har Krishan Public School", "Delhi", "Kalkaji")
    b = ensure_school(cms, "Guru Harkrishan Public School", "Delhi", "Kalkaji")
    c = ensure_school(cms, "Sri Sathya Sai Vidya Vihar", "Delhi", "Kalkaji")
    d = ensure_school(cms, "Shri Satya Sai Vidya Vihar School", "Delhi", "Kalkaji")
    assert a["id"] == b["id"] and c["id"] == d["id"]


def test_merge_keeps_different_schools_apart():
    out = merge({"a": ["DAV Public School", "Kalka Public School"], "b": ["Kalka Public School"]})
    assert len(out) == 2
