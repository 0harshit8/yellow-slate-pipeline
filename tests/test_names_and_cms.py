import pytest

from clients.cms_base import CMSError
from clients.cms_fake import FakeCMS
from stages.cms import ensure_school
from stages.names import cms_name, merge, normalize, school_email


def test_normalize_expands_short_forms_once():
    assert normalize("DPS R.K. Puram") == "delhi public school r k puram"
    assert normalize("Delhi Public School") == "delhi public school"
    assert normalize("DAV Public School") == "dav public school"


def test_cms_name_rule():
    assert cms_name("DPS", "Kalkaji") == "Delhi Public School Kalkaji"
    assert cms_name("Bal Bharati Public School Kalkaji", "Kalkaji") == "Bal Bharati Public School Kalkaji"
    assert cms_name("The British School", "Chanakyapuri") == "The British School Chanakyapuri"


def test_email():
    assert school_email("Delhi Public School Kalkaji") == "delhipublicschoolkalkaji@gmail.com"


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
    assert first["slug"] == "delhi/delhi-public-school-kalkaji-kalkaji"
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
