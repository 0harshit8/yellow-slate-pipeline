import os

from stages import research, topup

SHEET = """SCHOOL: ITM Global School
CMS_ID: 18889
PROFILE_URL: https://yellowslate.com/gwalior/itm-global-school
VERIFIED_VIA: https://saras.cbse.gov.in/SARAS/AffiliatedList/AfflicationDetails/1030283

CURRICULUM: CBSE | source: https://saras.cbse.gov.in/1030283
GRADES: Nursery to Class 12 | source: https://saras.cbse.gov.in/1030283
ESTABLISHED: 2017 | source: https://saras.cbse.gov.in/1030283
MEDIUM: English | source: https://careers360.com/itm-global
CO_ED: Yes | source: https://saras.cbse.gov.in/1030283
ADDRESS: AH-43 By-Pass, Turari, Gwalior 474001
FACILITIES: Library, labs, swimming pool, sports academy

FEES: Class 1: 55000, Class 10: 72000
FEES_SOURCE: Ezyschooling
FEES_NOTE: OMIT

ADMISSIONS: Forms open in January at the school office.

REVIEWS_BASE: no parent rating found
REVIEWS: BLOCKED | https://www.justdial.com/Gwalior/Itm-Global-School/9999PX751_BZDET
REVIEWS_SOURCE: NONE

IMAGE_URL: NONE

THREE_FACTS:
  1. Cambridge and CBSE on one campus.
  2. Boarding houses are air conditioned.
  3. Equestrian arena on site.

GAPS: No UDISE page; CBSE SARAS used instead.
CONFLICTS: SARAS gives 2017, Careers360 gives 2014. Registry value printed.
NO_EVIDENCE: OMIT
SEARCHES_USED: 7
"""


def _store(monkeypatch, tmp_path, text=SHEET, cms_id="18889"):
    store = tmp_path / "store"
    store.mkdir(exist_ok=True)
    (store / f"{cms_id}.md").write_text(text, encoding="utf-8")
    monkeypatch.setattr(research, "store_dir", lambda: str(store))
    return store


# --- what still needs a browser -------------------------------------------------------- #

def test_a_blocked_field_needs_a_browser_and_keeps_its_url():
    fields = research.parse_sheet(SHEET)
    assert "reviews" in topup.needs(fields)
    assert topup._url(fields["REVIEWS"]["value"]).startswith("https://www.justdial.com/")


def test_reviews_blocked_is_work_and_a_missing_photo_is_not():
    assert set(topup.needs(research.parse_sheet(SHEET))) == {"reviews"}


def test_a_complete_sheet_needs_nothing():
    text = (SHEET.replace("REVIEWS: BLOCKED | https://www.justdial.com/Gwalior/Itm-Global-School/9999PX751_BZDET",
                          "REVIEWS:\n  Academics: 80/20")
                 )
    assert topup.needs(research.parse_sheet(text)) == []


def test_fees_that_came_off_an_aggregator_because_the_real_table_was_a_scan():
    # FEES has a value, so the field alone looks fine. The note is what gives it away.
    text = SHEET.replace("FEES_NOTE: OMIT",
                         "FEES_NOTE: the school's 2026-27 PDF is a scan nobody could read")
    assert "fees" in topup.needs(research.parse_sheet(text))


def test_every_way_a_researcher_has_phrased_an_unreadable_fee_table():
    # Taken verbatim from the stored Gwalior sheets. "would not render" was missed at first,
    # which left Doon Public School out of a worklist it belonged in.
    for note in ("The school's own 2026-27 fee PDF exists but would not render (see GAPS).",
                 'The official "Fee Structure 2026-27" PDF is a scanned image that could not be read.',
                 "The school's 2026-27 fee table is an image which I could not read.",
                 "Doon's PDF is image-based."):
        text = SHEET.replace("FEES_NOTE: OMIT", f"FEES_NOTE: {note}")
        assert "fees" in topup.needs(research.parse_sheet(text)), note


# --- patching a stored sheet ------------------------------------------------------------ #

def test_a_patch_replaces_its_own_field_and_leaves_the_rest_byte_identical():
    out = topup.patch_text(SHEET, {"IMAGE_URL": "https://itmglobal.in/img/header/10.jpg"})
    before, after = research.parse_sheet(SHEET), research.parse_sheet(out)
    assert after["IMAGE_URL"]["value"] == "https://itmglobal.in/img/header/10.jpg"
    for name in before:
        if name != "IMAGE_URL":
            assert after[name]["value"] == before[name]["value"]


def test_a_multiline_reviews_value_keeps_its_indented_categories():
    out = topup.patch_text(SHEET, {"REVIEWS": "\n  Academics: 80/20\n  Management: 60/40"})
    fields = research.parse_sheet(out)
    assert "Academics: 80/20" in fields["REVIEWS"]["value"]
    assert "Management: 60/40" in fields["REVIEWS"]["value"]
    # the field after it must survive being written past
    assert fields["REVIEWS_SOURCE"]["value"] == "NONE"


def test_a_field_the_sheet_does_not_have_is_appended():
    out = topup.patch_text(SHEET, {"TOPUP": "2026-10-28 | IMAGE_URL"})
    assert research.parse_sheet(out)["TOPUP"]["value"] == "2026-10-28 | IMAGE_URL"


def test_apply_writes_the_sheet_and_stamps_it(monkeypatch, tmp_path):
    store = _store(monkeypatch, tmp_path)
    path = str(store / "18889.md")
    changed, problem = topup.apply_patch(path, {"IMAGE_URL": "https://itmglobal.in/img/header/10.jpg"})
    assert problem is None and changed == ["IMAGE_URL"]
    fields = research.parse_sheet(open(path, encoding="utf-8").read())
    assert fields["IMAGE_URL"]["value"] == "https://itmglobal.in/img/header/10.jpg"
    assert "IMAGE_URL" in fields["TOPUP"]["value"]


def test_a_patch_that_would_clobber_a_field_it_does_not_own_is_refused(monkeypatch, tmp_path):
    # A value carrying its own field line would silently rewrite FACILITIES. The sheet is the
    # only copy of research that cost real money, so nothing is written at all.
    store = _store(monkeypatch, tmp_path)
    path = str(store / "18889.md")
    kept = open(path, encoding="utf-8").read()
    changed, problem = topup.apply_patch(path, {"REVIEWS": "\n  Academics: 80/20\nFACILITIES: junk"})
    assert changed == [] and "FACILITIES" in problem
    assert open(path, encoding="utf-8").read() == kept


def test_an_empty_patch_changes_nothing(monkeypatch, tmp_path):
    store = _store(monkeypatch, tmp_path)
    path = str(store / "18889.md")
    kept = open(path, encoding="utf-8").read()
    assert topup.apply_patch(path, {}) == ([], None)
    assert open(path, encoding="utf-8").read() == kept


# --- the worklist ------------------------------------------------------------------------ #

def test_worklist_names_the_gaps_and_separates_schools_with_no_sheet(monkeypatch, tmp_path):
    _store(monkeypatch, tmp_path)
    work, no_sheet = topup.worklist([
        {"id": "18889", "name": "ITM Global School", "city": "Gwalior", "area": "Turari"},
        {"id": "99999", "name": "Never Researched School", "city": "Gwalior", "area": ""},
    ])
    assert len(work) == 1 and no_sheet == ["Never Researched School"]
    assert set(work[0]["needs"]) == {"reviews"}
    assert work[0]["urls"]["reviews"].startswith("https://www.justdial.com/")


def test_a_school_whose_sheet_is_complete_is_not_in_the_worklist(monkeypatch, tmp_path):
    good = (SHEET.replace("REVIEWS: BLOCKED | https://www.justdial.com/Gwalior/Itm-Global-School/9999PX751_BZDET",
                          "REVIEWS:\n  Academics: 80/20")
                 )
    _store(monkeypatch, tmp_path, text=good)
    work, no_sheet = topup.worklist([{"id": "18889", "name": "ITM Global School"}])
    assert work == [] and no_sheet == []


def test_read_patches_accepts_both_shapes(tmp_path):
    as_list = tmp_path / "a.json"
    as_list.write_text('[{"id": "18889", "fields": {"IMAGE_URL": "x"}}]', encoding="utf-8")
    as_map = tmp_path / "b.json"
    as_map.write_text('{"18889": {"IMAGE_URL": "x"}}', encoding="utf-8")
    assert topup.read_patches(str(as_list)) == topup.read_patches(str(as_map))


# --- P2: a broken sheet must not reach the shared store ---------------------------------- #

def test_a_partial_sheet_is_not_cached_for_the_next_blog(monkeypatch, tmp_path):
    # A stored sheet is marked ALREADY ON DISK, so no researcher is spawned to repair it.
    # Caching a known-bad one would keep producing bad blogs for MAX_AGE_DAYS.
    store = tmp_path / "store"
    monkeypatch.setattr(research, "store_dir", lambda: str(store))
    folder = tmp_path / "run"
    (folder / research.SHEET_DIR).mkdir(parents=True)
    (folder / research.SHEET_DIR / "18889.md").write_text(
        SHEET.replace("FEES: Class 1: 55000, Class 10: 72000", ""), encoding="utf-8")
    problems = research.save_to_store(str(folder))
    assert any("not stored for reuse" in p for p in problems)
    assert not os.path.exists(str(store / "18889.md"))


def test_a_clean_sheet_still_reaches_the_store(monkeypatch, tmp_path):
    store = tmp_path / "store"
    monkeypatch.setattr(research, "store_dir", lambda: str(store))
    folder = tmp_path / "run"
    (folder / research.SHEET_DIR).mkdir(parents=True)
    (folder / research.SHEET_DIR / "18889.md").write_text(SHEET, encoding="utf-8")
    assert research.save_to_store(str(folder)) == []
    assert os.path.exists(str(store / "18889.md"))


def test_a_marker_that_explains_itself_still_counts_as_empty():
    # Marker shapes taken verbatim from the stored Gwalior sheets. Each was read as a real
    # value, so the school was left out of a worklist it belonged in and shipped with a gap.
    for value in ("NONE (Justdial lists the Turari branch but shows no rating)",
                  "NONE. The only pages found are on thegurukulam.school. No rating is given.",
                  "NOT_FOUND for Dal Bazar."):
        text = SHEET.replace(
            "REVIEWS: BLOCKED | https://www.justdial.com/Gwalior/Itm-Global-School/9999PX751_BZDET",
            f"REVIEWS: {value}")
        assert "reviews" in topup.needs(research.parse_sheet(text)), value


def test_a_real_url_is_not_mistaken_for_a_marker():
    # _head stops at the first ':', so a bare https:// URL must not read as an empty marker.
    text = SHEET.replace(
        "REVIEWS: BLOCKED | https://www.justdial.com/Gwalior/Itm-Global-School/9999PX751_BZDET",
        "REVIEWS: https://www.justdial.com/Gwalior/Itm-Global-School/9999PX751_BZDET")
    assert "reviews" not in topup.needs(research.parse_sheet(text))


def test_a_topped_up_fee_table_is_not_offered_for_a_second_browser_run():
    # Reading a scan successfully leaves a note that says "scan", which is exactly what the
    # UNREADABLE heuristic looks for. Without the TOPUP line that note sends the school
    # straight back onto the worklist and the browser work gets paid for twice.
    text = SHEET.replace("FEES_NOTE: OMIT",
                         "FEES_NOTE: Class-wise table read from the school's own scanned PDF.")
    assert "fees" in topup.needs(research.parse_sheet(text))
    text += "\nTOPUP: 2026-10-28 | FEES, FEES_NOTE, FEES_SOURCE\n"
    assert "fees" not in topup.needs(research.parse_sheet(text))


def test_a_second_patch_keeps_what_the_first_one_recorded(tmp_path):
    path = tmp_path / "18889.md"
    path.write_text(SHEET, encoding="utf-8")
    topup.apply_patch(str(path), {"FEES": "Classes I-IV: Rs 61,000"})
    topup.apply_patch(str(path), {"IMAGE_URL": "https://itmglobal.in/img/header/10.jpg"})
    recorded = topup.topped_up(research.parse_sheet(path.read_text(encoding="utf-8")))
    assert {"FEES", "IMAGE_URL"} <= recorded
