import json
import os
import time

from stages import research

SHEET = """SCHOOL: Sri R.v. School
CMS_ID: 23222
PROFILE_URL: https://yellowslate.com/kolar/sri-rv-school
VERIFIED_VIA: https://schools.org.in/kolar/29201300123/sri-rv-school.html

CURRICULUM: State Board (KSEEB) | source: https://schools.org.in/kolar/29201300123.html
GRADES: Class 1 to Class 10 | source: https://schools.org.in/kolar/29201300123.html
ESTABLISHED: 1983 | source: https://srivschool.in/about
MEDIUM: English | source: https://schools.org.in/kolar/29201300123.html
CO_ED: Yes | source: https://schools.org.in/kolar/29201300123.html
ADDRESS: New Extension, Kolar, Karnataka 563101 | source: https://schools.org.in/kolar/29201300123.html
FACILITIES: Library, playground, computer lab

FEES: Class 1: 18000, Class 10: 24000
FEES_SOURCE: Uniapply.com
FEES_NOTE: OMIT

ADMISSIONS: Applications open in January at the school office; 2026-27 dates are unpublished.

REVIEWS_BASE: 4.1 stars over 225 Justdial ratings
REVIEWS:
  Academics: 82/18
  Infrastructure: 74/26
REVIEWS_SOURCE: https://www.justdial.com/Kolar/Sri-R-V-School

IMAGE_URL: https://srivschool.in/img/campus.jpg

THREE_FACTS:
  1. Running since 1983 on the New Extension campus.
  2. UDISE code 29201300123.
  3. Ten classrooms recorded in the 2024-25 UDISE return.

GAPS: NONE
CONFLICTS: NONE
NO_EVIDENCE: NO
SEARCHES_USED: 7
"""


def _run(tmp_path, files, schools=None):
    folder = tmp_path / "best-schools-in-kolar"
    (folder / research.SHEET_DIR).mkdir(parents=True)
    for name, text in files.items():
        (folder / research.SHEET_DIR / name).write_text(text, encoding="utf-8")
    problems = research.collect(str(folder), schools)
    index = folder / research.SHEET_DIR / research.INDEX
    data = json.loads(index.read_text(encoding="utf-8")) if index.exists() else None
    return problems, data


def test_a_saved_sheet_is_indexed_with_every_field_and_its_source(tmp_path):
    """The fields the blog never prints are the point: medium, co-ed, the postal address and
    the grade range are what their CRM form needs to make a created school's page public, and
    a field without its source URL is not much use for filling that form later."""
    problems, data = _run(tmp_path, {"23222.md": SHEET},
                          schools=[{"name": "Sri R.v. School", "id": "23222"}])
    assert problems == []
    school, = data["schools"]
    assert school["cms_id"] == "23222"
    assert school["school"] == "Sri R.v. School"
    assert school["file"] == "research/23222.md"
    assert school["missing"] == [] and school["crm_missing"] == []
    fields = school["fields"]
    assert fields["MEDIUM"] == {
        "value": "English", "source": "https://schools.org.in/kolar/29201300123.html"}
    assert fields["CO_ED"]["value"] == "Yes"
    assert fields["ADDRESS"]["value"] == "New Extension, Kolar, Karnataka 563101"
    assert fields["GRADES"]["value"] == "Class 1 to Class 10"
    assert fields["SEARCHES_USED"]["value"] == "7"
    # The indented review and fact lines belong to the field above them, not to a field of
    # their own, and the sheet's own order survives.
    assert fields["REVIEWS"]["value"] == "Academics: 82/18\nInfrastructure: 74/26"
    assert fields["THREE_FACTS"]["value"].startswith("1. Running since 1983")
    assert list(fields) == [f for f in research.FIELDS if f in fields]


def test_the_sheet_file_itself_is_left_exactly_as_it_came_back(tmp_path):
    folder = tmp_path / "b"
    (folder / research.SHEET_DIR).mkdir(parents=True)
    (folder / research.SHEET_DIR / "23222.md").write_text(SHEET, encoding="utf-8")
    research.collect(str(folder), [{"name": "Sri R.v. School", "id": "23222"}])
    assert (folder / research.SHEET_DIR / "23222.md").read_text(encoding="utf-8") == SHEET


def test_a_malformed_sheet_is_reported_and_the_run_goes_on(tmp_path):
    """Losing the blog because one fact sheet could not be parsed would be a worse failure
    than today's, so a sheet with nothing field-shaped in it is kept on disk, reported, and
    left out of the index. The good sheet beside it is still indexed."""
    problems, data = _run(tmp_path, {
        "23222.md": SHEET,
        "23228.md": "I could not find anything for this school, sorry.\n\n- tried Justdial\n"})
    assert [s["cms_id"] for s in data["schools"]] == ["23222"]
    assert any("23228.md" in p and "no fields parsed" in p for p in problems)
    assert (tmp_path / "best-schools-in-kolar" / research.SHEET_DIR / "23228.md").exists()


def test_a_partial_sheet_keeps_what_it_has(tmp_path):
    problems, data = _run(tmp_path, {"23228.md": (
        "SCHOOL: JSS Public School\nCMS_ID: 23228\n"
        "CURRICULUM: CBSE | source: https://cbse.gov.in/saras/23228\nFEES: NOT_FOUND\n")})
    school, = data["schools"]
    assert school["fields"]["CURRICULUM"]["source"] == "https://cbse.gov.in/saras/23228"
    assert "MEDIUM" in school["missing"] and "GRADES" in school["missing"]
    assert school["crm_missing"] == ["MEDIUM", "CO_ED", "GRADES"]
    assert any("partial sheet" in p for p in problems)


def test_a_sheet_inside_a_code_fence_still_parses(tmp_path):
    """The agent definition shows the sheet inside a fenced block, so a writer that copies it
    verbatim may copy the fences too. That is not a malformed sheet."""
    _, data = _run(tmp_path, {"23222.md": "```\n" + SHEET + "```\n"})
    assert data["schools"][0]["fields"]["MEDIUM"]["value"] == "English"


def test_a_school_with_no_sheet_at_all_is_named(tmp_path):
    problems, _ = _run(tmp_path, {"23222.md": SHEET}, schools=[
        {"name": "Sri R.v. School", "id": "23222"}, {"name": "JSS Public School", "id": "23228"}])
    assert any("JSS Public School (23228): no fact sheet in research/" in p for p in problems)
    assert not any("Sri R.v. School" in p for p in problems)


def test_a_school_whose_sheet_is_malformed_is_not_reported_as_missing(tmp_path):
    """An unparseable sheet and a sheet that never arrived need different fixes: one is on
    disk for a human to read, the other means the writer skipped the Write call."""
    problems, _ = _run(tmp_path, {"23228.md": "no sheet, just prose\n"},
                       schools=[{"name": "JSS Public School", "id": "23228"}])
    assert any("23228): its sheet did not parse" in p for p in problems)


def test_no_research_folder_is_a_problem_not_an_exception(tmp_path):
    folder = tmp_path / "empty-run"
    folder.mkdir()
    problems = research.collect(str(folder), [{"name": "A School", "id": "1"}])
    assert any("saved none of them" in p for p in problems)
    assert not os.path.exists(os.path.join(str(folder), research.SHEET_DIR, research.INDEX))


# Reuse across blogs. A city gets several keywords and every one of them used to re-research
# every school, at roughly 465k tokens each (measured on Bhubaneswar, Oct 2026).

def _store(monkeypatch, tmp_path):
    store = tmp_path / "store"
    monkeypatch.setattr(research, "store_dir", lambda: str(store))
    return store


def test_a_fresh_stored_sheet_is_copied_in_and_reported(monkeypatch, tmp_path):
    store = _store(monkeypatch, tmp_path)
    store.mkdir()
    (store / "23222.md").write_text(SHEET, encoding="utf-8")
    folder = tmp_path / "run"
    folder.mkdir()
    reused = research.reuse(str(folder), [{"id": "23222", "name": "Sri R.v. School"}])
    assert reused == {"23222"}
    assert (folder / research.SHEET_DIR / "23222.md").read_text(encoding="utf-8") == SHEET


def test_a_stale_sheet_is_not_reused(monkeypatch, tmp_path):
    store = _store(monkeypatch, tmp_path)
    store.mkdir()
    old = store / "23222.md"
    old.write_text(SHEET, encoding="utf-8")
    stale = time.time() - 200 * 86400
    os.utime(old, (stale, stale))
    folder = tmp_path / "run"
    folder.mkdir()
    assert research.reuse(str(folder), [{"id": "23222"}]) == set()
    assert not (folder / research.SHEET_DIR).exists()


def test_a_school_with_no_stored_sheet_is_not_reused(monkeypatch, tmp_path):
    _store(monkeypatch, tmp_path)
    folder = tmp_path / "run"
    folder.mkdir()
    assert research.reuse(str(folder), [{"id": "99999"}]) == set()


def test_save_to_store_then_reuse_round_trips(monkeypatch, tmp_path):
    _store(monkeypatch, tmp_path)
    first = tmp_path / "first"
    (first / research.SHEET_DIR).mkdir(parents=True)
    (first / research.SHEET_DIR / "23222.md").write_text(SHEET, encoding="utf-8")
    assert research.save_to_store(str(first)) == []
    second = tmp_path / "second"
    second.mkdir()
    assert research.reuse(str(second), [{"id": "23222"}]) == {"23222"}


def test_a_missing_store_is_not_an_error(monkeypatch, tmp_path):
    _store(monkeypatch, tmp_path)          # never created
    folder = tmp_path / "run"
    folder.mkdir()
    assert research.reuse(str(folder), [{"id": "23222"}]) == set()
    assert research.save_to_store(str(folder)) == []


def test_a_field_with_a_bracketed_qualifier_still_parses():
    # The researcher writes "FEES (2026-27, tuition per year):". A key that had to touch the
    # colon made that line ordinary text, so the fee table was swallowed by FACILITIES above
    # it and the sheet was reported as having no FEES at all.
    text = SHEET.replace("FEES: Class 1: 18000, Class 10: 24000",
                         "FEES (2026-27, tuition per year):\n  Class 1: 18000\n  Class 10: 24000")
    fields = research.parse_sheet(text)
    assert "18000" in fields["FEES"]["value"]
    assert "18000" not in fields["FACILITIES"]["value"]


def test_a_reused_sheet_does_not_get_its_age_reset(monkeypatch, tmp_path):
    # store -> run folder -> store used to stamp the sheet with today's date, so a school in
    # a city with several keywords stayed under MAX_AGE_DAYS forever and was never re-read.
    store = _store(monkeypatch, tmp_path)
    store.mkdir()
    kept = store / "23222.md"
    kept.write_text(SHEET, encoding="utf-8")
    aged = time.time() - 80 * 86400
    os.utime(kept, (aged, aged))

    folder = tmp_path / "run"
    folder.mkdir()
    assert research.reuse(str(folder), [{"id": "23222"}]) == {"23222"}
    assert research.save_to_store(str(folder)) == []
    assert abs(os.path.getmtime(kept) - aged) < 2
