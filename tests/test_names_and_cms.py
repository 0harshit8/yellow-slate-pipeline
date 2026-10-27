import pytest

from clients.cms_base import CMSError
from clients.cms_fake import FakeCMS
from stages.cms import ensure_school, UnplaceableSchool
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
    assert cms_name("Army Public School, Danapur Cantt.", "Danapur Cantt") == "Army Public School"


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


@pytest.fixture(autouse=True)
def no_web_lookup(monkeypatch):
    """The last-resort locality lookup is a Tavily search plus a Claude call. Not in tests."""
    from stages import area as area_stage
    monkeypatch.setattr(area_stage, "lookup_area", lambda school, city: "")


@pytest.fixture
def cms(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    # Real Delhi localities, so the fake can tell a new campus in a real place from a typo
    # the way their CMS does. See FakeCMS.known_areas.
    return FakeCMS(path=str(tmp_path / "fake.json"),
                   areas=["Kalkaji", "Saket", "Dwarka", "Hauz Khas", "Rohini"])


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
    """Two campuses of one chain are two CMS rows, and a city-wide search must not fold them.

    This is the hole a name + city search opens: with only the Kalkaji campus stored, a
    search for "Delhi Public School" in Delhi returns it at a perfect score even when the
    blog is about Saket. Taking that row would hang a Saket listicle off a Kalkaji school.
    """
    a = ensure_school(cms, "Delhi Public School", "Delhi", "Kalkaji")
    b = ensure_school(cms, "Delhi Public School", "Delhi", "Saket")
    assert a["id"] != b["id"]
    assert a["area"] == "Kalkaji" and b["area"] == "Saket"


def test_a_misspelt_locality_keeps_their_match_instead_of_creating(cms):
    """A locality their CMS has never heard of is a typo far more often than a new campus.

    "Kalkajee" is not a place, so creating under it would both duplicate the school and add
    a junk locality that splits Kalkaji's schools in two. Keep their row, flag it instead.
    """
    first = ensure_school(cms, "Delhi Public School", "Delhi", "Kalkaji")
    again = ensure_school(cms, "Delhi Public School", "Delhi", "Kalkajee")
    assert again["id"] == first["id"]
    assert again["review"] is True
    assert len(cms.schools) == 1


def test_the_area_recorded_is_the_one_their_cms_holds(cms):
    """Their area wins over the page's. The page is a guess, their CMS row is a fact."""
    ensure_school(cms, "Sahoday Senior Secondary School", "Delhi", "Hauz Khas")
    # the pages say nothing this time, and a city-wide search still places it correctly
    again = ensure_school(cms, "Sahoday Senior Secondary School", "Delhi", "")
    assert again["created"] is False
    assert again["area"] == "Hauz Khas"


def test_a_shared_name_is_placed_from_the_page_not_guessed(cms):
    """With the name in two localities their API refuses to choose, so the page decides."""
    dwarka = ensure_school(cms, "Kidzee", "Delhi", "Dwarka")
    kalkaji = ensure_school(cms, "Kidzee", "Delhi", "Kalkaji")
    assert dwarka["id"] != kalkaji["id"]
    again = ensure_school(cms, "Kidzee", "Delhi", "Kalkaji")
    assert again["id"] == kalkaji["id"]
    assert again["created"] is False


def test_a_shared_name_with_no_locality_is_dropped_not_duplicated(cms):
    """Nothing says which Kidzee this is, so the school leaves the blog. It never creates.

    Returning "not found" here is what used to add a third Kidzee to a CMS that had two.
    """
    ensure_school(cms, "Kidzee", "Delhi", "Dwarka")
    ensure_school(cms, "Kidzee", "Delhi", "Kalkaji")
    with pytest.raises(UnplaceableSchool):
        ensure_school(cms, "Kidzee", "Delhi", "", blog_area="")
    assert len(cms.schools) == 2


def test_one_locality_spelt_two_ways_is_not_a_second_campus(tmp_path, monkeypatch):
    """Their CMS holds "R. K. Puram" (with the schools) and "R.K. Puram" (empty) at once.

    Measured against their live CMS on Oct 16, 2026: area_exists says yes to both. Reading
    the empty twin as a real locality with no school of this name in it is the exact shape
    of "a campus they do not have", and acting on it adds a duplicate to a CMS that already
    had three rows for this school.
    """
    import config
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    cms = FakeCMS(path=str(tmp_path / "fake.json"),
                  areas=["R. K. Puram", "R.K. Puram", "Dwarka"])
    first = ensure_school(cms, "Delhi Public School", "Delhi", "R. K. Puram")
    again = ensure_school(cms, "Delhi Public School", "Delhi", "R.K. Puram")
    assert again["id"] == first["id"]
    assert again["created"] is False
    assert len(cms.schools) == 1


def test_two_numbered_blocks_are_still_two_campuses(tmp_path, monkeypatch):
    """The spelling rule must not swallow a real difference: GK and GK 1 are not one place."""
    import config
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    cms = FakeCMS(path=str(tmp_path / "fake.json"),
                  areas=["Greater Kailash", "Greater Kailash 1"])
    a = ensure_school(cms, "Bluebells School", "Delhi", "Greater Kailash")
    b = ensure_school(cms, "Bluebells School", "Delhi", "Greater Kailash 1")
    assert a["id"] != b["id"]
    assert len(cms.schools) == 2


def test_a_locality_that_cannot_scope_their_search_drops_one_school(cms):
    """A second search that comes back ambiguous must skip the school, not stop the batch.

    The locality is real enough to pass resolve() and unknown to their CMS, so the repeat
    search is handed an area they ignore and widens right back to the whole city - the same
    ambiguous answer as before. That is one school nobody can place, which UnplaceableSchool
    exists for. Letting the raw AmbiguousSchool out instead killed a whole run of eleven
    schools over one spelling.
    """
    ensure_school(cms, "Kidzee", "Delhi", "Dwarka")
    ensure_school(cms, "Kidzee", "Delhi", "Kalkaji")
    with pytest.raises(UnplaceableSchool):
        ensure_school(cms, "Kidzee", "Delhi", "Mandi House")
    assert len(cms.schools) == 2


def test_an_incomplete_cms_row_is_dropped_not_published(cms):
    """Their row 8010 has area null and slug "/dav-public-school-": a dead profile link.

    Nine schools with working links beat ten with one broken one, and the message names the
    row so it can be fixed at their end.
    """
    cms.schools.append({"id": 8010, "name": "DAV Public School", "slug": "/dav-public-school-",
                        "city": "Delhi", "area": "", "email": "dav@x.com",
                        "verified": False, "claimed": False})
    with pytest.raises(UnplaceableSchool) as caught:
        ensure_school(cms, "DAV Public School", "Delhi", "")
    assert "8010" in str(caught.value)


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


# ---- schools their CMS already had live, measured Oct 19, 2026 -------------------------------
#
# Three schools this pipeline "created" were already in their CMS, live, and the search missed
# them two different ways. Every one of them cost a row with Verified = No, which has no public
# page at all, so the blog carried a dead link and their team has to delete the row by hand.
# There is no delete call on the pipeline API, so these are the expensive mistake to prevent.


def _their_row(cms, **row):
    """Put a row of THEIRS in the store: a real id, their spelling, their slug."""
    cms.schools.append({"email": f"theirs-{row['id']}@example.com",
                        "verified": True, "claimed": False, **row})
    return row["id"]


@pytest.mark.parametrize("name, their_name, their_id", [
    ("Deepalaya School", "DEEPALAYA SCHOOL", 15236),
    ("Sri Satya Sai Vidya Vihar School", "Sri Satya Sai Vidya Vihar School", 21497),
])
def test_their_area_is_an_address_not_a_locality(tmp_path, monkeypatch, name, their_name, their_id):
    """Both of these were created although their CMS held them, because of one area string.

    Their rows 15236 and 21497 both sit in "Kalkaji Extension, Block A 10,Govindpuri" while
    every competitor page says "Kalkaji". The city-wide search found them. This stage then
    read that string as a different locality, searched Kalkaji, found nothing there, and
    concluded Kalkaji was a campus they do not have - so 23229 and 23231 were created.

    Their own search is no help: an area is matched on the exact characters, so even
    "Kalkaji Extension" comes back area_matched false. The comparison has to happen here.
    """
    import config
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    cms = FakeCMS(path=str(tmp_path / "fake.json"),
                  areas=["Kalkaji", "Kalkaji Extension, Block A 10,Govindpuri"])
    _their_row(cms, id=their_id, name=their_name, city="Delhi",
               area="Kalkaji Extension, Block A 10,Govindpuri",
               slug="delhi/" + their_name.lower().replace(" ", "-") + "-kalkaji-extension")

    got = ensure_school(cms, name, "Delhi", "Kalkaji")
    assert got["id"] == their_id, "their live row, not a second one"
    assert got["created"] is False
    assert got["area"] == "Kalkaji Extension, Block A 10,Govindpuri", "record THEIR area"
    assert len(cms.schools) == 1


def test_a_campus_suffix_in_their_name_is_found_before_creating(tmp_path, monkeypatch):
    """Their 714 is "Glendale Academy - Sun City Campus", filed under "Rajendranagar mandal".

    Measured against their live API: "Glendale Academy" in Hyderabad returns not_found even
    when the search is scoped to that row's own area, because the suffix costs it too much
    score. "Glendale Academy Sun City" returns it at 0.875. So the plain name could not see
    a school that was already there and 23236 was created.

    The locality the pages gave has to go into the NAME to reach it. Their area is one no
    page mentioned, so the match is flagged for review rather than taken quietly.
    """
    import config
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    cms = FakeCMS(path=str(tmp_path / "fake.json"),
                  areas=["Sun City", "Rajendranagar mandal"])
    _their_row(cms, id=714, name="Glendale Academy - Sun City Campus", city="Hyderabad",
               area="Rajendranagar mandal",
               slug="hyderabad/glendale-academy-sun-city-campus-rajendranagar-mandal")

    got = ensure_school(cms, "Glendale Academy", "Hyderabad", "Sun City")
    assert got["id"] == 714, "their live row, not a second one"
    assert got["created"] is False
    assert got["review"] is True, "their area is one no page named, so a human should see it"
    assert len(cms.schools) == 1


def test_a_locality_in_their_name_is_not_enough_on_its_own(tmp_path, monkeypatch):
    """The campus rung must not hand back a school whose name does not name that campus.

    Appending the locality to the name is a loose search on purpose, so the row it finds has
    to carry the locality in its own name - that is the only thing that makes it a campus row
    rather than a good score. Without the check, any chain row in the city would do.
    """
    import config
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    cms = FakeCMS(path=str(tmp_path / "fake.json"), areas=["Sun City", "Kondapur"])
    _their_row(cms, id=963, name="Glendale Academy", city="Hyderabad", area="Kondapur",
               slug="hyderabad/glendale-academy-kondapur")

    got = ensure_school(cms, "Glendale Academy", "Hyderabad", "Sun City")
    assert got["created"] is True, "Kondapur is a different campus, so Sun City is new"
    assert got["id"] != 963
    assert got["review"] is True, "they hold this name elsewhere, so say so"
    assert "Kondapur" in got["note"]


def test_two_real_schools_of_one_name_stay_two_schools(tmp_path, monkeypatch):
    """The Kolar pair that any rule here has to survive: 23209 and 23228.

    "JSS Public School" in Nehru Extention and "JSS Public School" in Malur are two different
    schools, both correctly created. Nothing about the new area comparison or the campus rung
    may fold them into one.
    """
    import config
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    cms = FakeCMS(path=str(tmp_path / "fake.json"), areas=["Nehru Extention", "Malur"])

    nehru = ensure_school(cms, "JSS Public School", "Kolar", "Nehru Extention")
    malur = ensure_school(cms, "JSS Public School", "Kolar", "Malur")
    assert nehru["id"] != malur["id"]
    assert nehru["area"] == "Nehru Extention" and malur["area"] == "Malur"
    assert len(cms.schools) == 2


def test_a_full_candidate_list_stops_a_create_instead_of_guessing(tmp_path, monkeypatch):
    """Their candidate list stops at five, so a FULL list is a cut-off list.

    Measured Oct 19, 2026: "Delhi Public School" in Delhi returns exactly 5 candidates and
    their CMS plainly holds more, and "Oakridge International School" in Hyderabad returns 5.
    So a locality missing from a full list is not a locality they do not have, it is one this
    search cannot see - and creating on that is how 23238 Oakridge International School
    (Manikonda) was added against five existing rows. One school reported beats a duplicate
    published, so the school is skipped with their areas named.
    """
    import config
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    theirs = ["Bowrampet", "Bachupally", "Gachibowli", "Khajaguda", "Kondapur"]
    cms = FakeCMS(path=str(tmp_path / "fake.json"), areas=theirs + ["Manikonda"])
    for i, area in enumerate(theirs):
        _their_row(cms, id=600 + i, name="Oakridge International School", city="Hyderabad",
                   area=area, slug=f"hyderabad/oakridge-international-school-{area.lower()}")

    with pytest.raises(UnplaceableSchool) as caught:
        ensure_school(cms, "Oakridge International School", "Hyderabad", "Manikonda")
    assert "Manikonda" in str(caught.value)
    assert "Area column" in str(caught.value)
    assert len(cms.schools) == 5, "nothing created"


def test_a_short_candidate_list_is_the_whole_set_so_a_new_campus_is_still_created(tmp_path, monkeypatch):
    """The cap rule must not stop a genuine new campus of a chain they only partly hold.

    Four rows back for "Guru Harkrishan Public School" is the complete set, so a locality
    none of them is in really is a campus they do not have. Refusing these would drop good
    schools out of blogs for no reason, which is the mistake the old area gate made.
    """
    import config
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    theirs = ["Mayapuri", "Greater Kailash", "Shahdara", "Anand Vihar"]
    cms = FakeCMS(path=str(tmp_path / "fake.json"), areas=theirs + ["Kalkaji"])
    for i, area in enumerate(theirs):
        _their_row(cms, id=15000 + i, name="Guru Harkrishan Public School", city="Delhi",
                   area=area, slug=f"delhi/guru-harkrishan-public-school-{area.lower()}")

    got = ensure_school(cms, "Guru Harkrishan Public School", "Delhi", "Kalkaji")
    assert got["created"] is True
    assert got["area"] == "Kalkaji"
    assert len(cms.schools) == 5


def test_merge_keeps_different_schools_apart():
    out = merge({"a": ["DAV Public School", "Kalka Public School"], "b": ["Kalka Public School"]})
    assert len(out) == 2


# ---- a school with parent ratings outranks one without ---------------------------------------

def test_merge_ranks_a_rated_school_above_a_better_listed_one():
    """Three listicles naming a school do not beat one directory showing real parent ratings.

    This is what filled the Kolar post with schools nobody had reviewed: consensus alone put
    them first, and their review graphs had nothing to draw.
    """
    out = merge({
        "a": [{"name": "Listicle Favourite School", "area": "Tamaka"}],
        "b": [{"name": "Listicle Favourite School", "area": "Tamaka"}],
        "c": [{"name": "Listicle Favourite School", "area": "Tamaka"}],
        "d": [{"name": "Well Reviewed School", "area": "Cottonpet", "reviews": 186}],
    })
    assert out[0]["name"] == "Well Reviewed School"
    assert out[0]["reviews"] == 186
    assert out[1]["name"] == "Listicle Favourite School"
    assert out[1]["count"] == 3


def test_merge_keeps_the_largest_review_count_any_page_gave():
    out = merge({
        "a": [{"name": "Chinmaya Vidyalaya", "area": "Cottonpet", "reviews": 186}],
        "b": [{"name": "Chinmaya Vidyalaya", "area": "Cottonpet", "reviews": 210}],
        "c": [{"name": "Chinmaya Vidyalaya", "area": "Cottonpet"}],
    })
    assert len(out) == 1
    assert out[0]["reviews"] == 210


def test_merge_still_ranks_unrated_schools_by_consensus():
    out = merge({
        "a": ["Quiet School", "Popular School"],
        "b": ["Popular School"],
    })
    assert [s["name"] for s in out] == ["Popular School", "Quiet School"]
    assert all(s["reviews"] == 0 for s in out)


def test_merge_ignores_a_review_count_that_is_not_a_number():
    out = merge({"a": [{"name": "A School", "area": "", "reviews": "lots"}]})
    assert out[0]["reviews"] == 0


# ---- the city is not a locality, so it must not split a school in two ------------------------

def test_merge_folds_a_city_as_area_entry_into_the_real_locality():
    """The bug the live Kolar pick showed on Oct 15, 2026:

        119 ratings  area=Mulbagal  Gnana Jyothi School
          0 ratings  area=Kolar     Gnana Jyothi School

    One school, two rows. prompts/pick_extract.md tells the extractor to fall back to the
    city name when a page gives no locality at all, so area = city means "unknown", exactly
    like the empty string _same_place already lets through. Treating it as a locality that
    clashes with Mulbagal cost a shortlist slot and left a twin with no review signal that
    could be picked instead of the real row.
    """
    out = merge({
        "justdial": [{"name": "Gnana Jyothi School", "area": "Mulbagal", "reviews": 119}],
        "listicle": [{"name": "Gnana Jyothi School", "area": "Kolar"}],
    }, city="Kolar")
    assert len(out) == 1, "area = city means unknown, so it must not split the school"
    assert out[0]["area"] == "Mulbagal", "the real locality wins over the city fallback"
    assert out[0]["reviews"] == 119
    assert out[0]["count"] == 2


def test_merge_never_records_the_city_as_the_area():
    """With no page naming a locality, the area stays unknown rather than becoming the city.

    An area named after its own city is their CMS catch-all and holds no schools - see
    is_city_area() in stages/area.py. Recording it here would hand the cms stage a locality
    that every search misses, which is how the duplicate bug started.
    """
    out = merge({"a": [{"name": "Jyothi English Medium School", "area": "Kolar"}]}, city="Kolar")
    assert out[0]["area"] == "", "an unknown locality stays empty for stages/area.py to resolve"


def test_merge_still_keeps_two_localities_apart_when_a_city_is_given():
    out = merge({
        "a": [{"name": "Sandeepani Public School", "area": "Bangarapet"}],
        "b": [{"name": "Sandeepani Public School", "area": "Mulbagal"}],
    }, city="Kolar")
    assert len(out) == 2, "two stated localities are still two different schools"


def test_merge_treats_the_city_as_a_locality_when_no_city_was_given():
    """The rule fires on the city merge() was told about, nothing else.

    "Kolar" is a locality in its own right to a caller that named no city, and guessing which
    of two names is a city would need their CMS, which this module deliberately cannot reach.
    """
    out = merge({
        "a": [{"name": "Some School", "area": "Kolar"}],
        "b": [{"name": "Some School", "area": "Mulbagal"}],
    })
    assert len(out) == 2
