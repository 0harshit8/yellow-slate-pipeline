import os

from stages.qc import check_blog

HERE = os.path.join(os.path.dirname(__file__), "fixtures")
KW = "schools in Kalkaji"


def load():
    with open(os.path.join(HERE, "good_blog.md"), encoding="utf-8") as fh:
        return fh.read()


def fails(lines):
    return [l for l in lines if l.startswith("FAIL")]


def test_good_blog_passes():
    passed, lines = check_blog(load(), KW, expected_ids=["900001", "900002"])
    assert passed, fails(lines)


def test_empty_admission_id_fails():
    md = load().replace('id="900002"', 'id=""')
    passed, lines = check_blog(md, KW, expected_ids=["900001", "900002"])
    assert not passed
    assert any("empty btn_admissions id" in l for l in fails(lines))


def test_wrong_bullet_count_fails():
    md = load().replace("- Known for sports.\n", "")
    passed, lines = check_blog(md, KW)
    assert any("2 intro bullets" in l for l in fails(lines))


def test_edustoke_link_fails():
    md = load().replace("Source: Delhi Public School Kalkaji Official Website",
                        "Source: [Edustoke](https://www.edustoke.com/x)")
    passed, lines = check_blog(md, KW)
    assert any("Edustoke" in l for l in fails(lines))


def test_missing_fee_source_fails():
    md = load().replace("Source: Delhi Public School Kalkaji Official Website", "")
    passed, lines = check_blog(md, KW)
    assert any("no Source: line" in l for l in fails(lines))


def test_too_few_faqs_fails():
    md = load().split("### When do admissions open?")[0]
    passed, lines = check_blog(md, KW)
    assert any("FAQs, need 5+" in l for l in fails(lines))


def test_missing_graph_and_external_image_fail():
    md = load().replace("![Parent sentiment breakdown for Bal Bharati Public School Kalkaji](graphs/bbps.png)", "")
    md = md.replace("(images/dps.jpg)", "(https://example.com/dps.jpg)")
    passed, lines = check_blog(md, KW)
    f = " ".join(fails(lines))
    assert "no parent review graph" in f
    assert "external URL" in f


def test_uppercase_read_more_link_fails():
    md = load().replace('link="/school/delhi/delhi-public-school-kalkaji-kalkaji"',
                        'link="/school/Delhi/DPS Kalkaji"')
    passed, lines = check_blog(md, KW)
    assert any("read_more_blogs" in l for l in fails(lines))


def test_h1_fails_and_meta_checked():
    passed, lines = check_blog("# Title\n\n" + load(), KW)
    assert any("no H1" in l for l in fails(lines))
    passed, lines = check_blog(load(), KW, meta={"title": "Best Schools in Kalkaji", "meta_title": "x", "meta_description": "d"})
    assert any("meta title" in l for l in fails(lines))


def test_missing_photo_is_only_a_warning():
    md = load().replace("![Bal Bharati Public School Kalkaji](images/bbps.jpg)\n", "")
    passed, lines = check_blog(md, KW, expected_ids=["900001", "900002"])
    assert passed, fails(lines)
    assert any(l.startswith("WARN") and "no school image" in l for l in lines)


# ---- a school count claimed in the meta must match the post ---------------------------------

def meta_with(description="", title="Best Schools in Kalkaji", meta_title="Best Schools in Kalkaji"):
    return {"title": title, "meta_title": meta_title, "meta_description": description}


def test_a_stale_meta_count_fails():
    """The Kolar post shipped this: a school was dropped by hand and meta.json kept the old
    number, so the description promised ten schools over a post that listed nine. Every other
    meta rule passed, because they only ask whether a description is there at all.
    """
    passed, lines = check_blog(load(), KW, meta=meta_with("Fee details for 3 CBSE schools in Kalkaji."))
    assert not passed
    assert any("meta says 3, the post has 2" in l for l in fails(lines))


def test_a_matching_meta_count_passes():
    passed, lines = check_blog(load(), KW, meta=meta_with("Fee details for 2 CBSE schools in Kalkaji."))
    assert passed, fails(lines)


def test_a_count_in_the_title_is_checked_too():
    passed, lines = check_blog(load(), KW, meta=meta_with(
        "Fees, admission and reviews.", title="Top 7 Schools in Kalkaji", meta_title="Top 7 Schools in Kalkaji"))
    assert any("meta says 7, the post has 2" in l for l in fails(lines))


def test_a_meta_claiming_no_count_is_left_alone():
    """Most descriptions never state a number, and inventing a complaint about that would
    fail every blog that reads naturally."""
    passed, lines = check_blog(load(), KW, meta=meta_with(
        "Compare curriculum, grades, location, admission and fees for the best schools in Kalkaji."))
    assert passed, fails(lines)
    assert not any("school count" in l for l in lines)


def test_a_session_year_is_not_a_school_count():
    """"2026-27" sits in every title this pipeline writes, and "27" must not read as a count."""
    passed, lines = check_blog(load(), KW, meta=meta_with(
        "Best schools in Kalkaji 2026-27: fees and admission for 2 schools.",
        title="Best Schools in Kalkaji 2026-27", meta_title="Best Schools in Kalkaji 2026-27"))
    assert passed, fails(lines)


def test_a_class_number_is_not_a_school_count():
    passed, lines = check_blog(load(), KW, meta=meta_with(
        "Compare Class 10 schools in Kalkaji on fees, admission and parent reviews."))
    assert passed, fails(lines)


# ---- a researched gap is allowed to be stated; an unresearched one is not -------------------

def test_a_fee_section_that_only_says_contact_the_school_fails():
    """The old gate read the phrase as a licence: `elif "contact the school" not in fee.lower()`
    skipped every fee check when it was present, so 28 of 79 published school sections carry
    no fee information and QC passed all of them. Kalka Public School Kalkaji shipped that way
    while SchoolsUniverse, Careers360 and Uniapply each published a figure for it.
    """
    md = load().replace(
        "The published annual fee is about Rs. 95,000 for the 2026-27 session. "
        "Class-wise figures are not published.\n\nSource: Careers360",
        "Contact the school for the latest details.")
    passed, lines = check_blog(md, KW)
    assert not passed
    assert any("fee section has no amount" in l for l in fails(lines))


def test_an_admission_section_that_only_says_contact_the_school_fails():
    md = load().replace("- Apply at the school office.",
                        "Contact the school for the latest details.")
    passed, lines = check_blog(md, KW)
    assert not passed
    assert any("admission section has no process" in l for l in fails(lines))


def test_an_admission_section_may_say_contact_the_school_about_the_dates():
    """The narrow licence stays: current-cycle dates and seat vacancies genuinely are not
    published ahead of time. What is not allowed is a section made only of that sentence."""
    md = load().replace(
        "- Apply at the school office.",
        "- Registration opens online in December and closes in January.\n"
        "- Shortlisted families are called for an interaction.\n"
        "- Contact the school for the latest details on this year's exact dates.")
    passed, lines = check_blog(md, KW)
    assert passed, fails(lines)


def test_a_review_section_with_no_percentages_fails():
    """Five published schools carry a Parent Review heading with no numbers under it."""
    md = load().replace("- 75% positive on sports", "- Parents speak well of the school.")
    passed, lines = check_blog(md, KW)
    assert not passed
    assert any("review section has no percentages" in l for l in fails(lines))


# --------------------------------------------------------------------------- #
# Documented absences. A fee or a parent review that no source publishes cannot be
# written, and before this a school like Hill View (Kalkaji, Oct 2026: ten sources
# tried, nothing found) could never pass. The escape turns those FAILs into WARNs,
# but only when notes.md records what was tried, so an absence has to be researched
# and written down rather than merely asserted. qc_pass still goes to a human.

ABSENCES = """## Documented absences
- Delhi Public School Kalkaji | fee | Ezyschooling gated the table, Uniapply says unavailable, Careers360 and SchoolMyKids carry no listing, no official site and no UDISE record
- Delhi Public School Kalkaji | reviews | no ratings on Justdial, Google Maps, Sulekha, Facebook or MouthShut, and the school has no official page
"""


def no_fee_amount(md):
    """School 1's fee table and amount removed, its Source line kept."""
    return md.replace("| Class | Annual Fee |\n| --- | --- |\n| Nursery | 1,20,000 |\n",
                      "Fees are not published.\n", 1)


def no_reviews(md):
    """School 1's review percentage and sentiment graph removed."""
    md = md.replace("- 80% positive on academics", "- Parents speak warmly of the staff", 1)
    return md.replace(
        "![Parent sentiment breakdown for Delhi Public School Kalkaji](graphs/dps.png)\n", "", 1)


def test_undocumented_fee_absence_still_fails():
    passed, lines = check_blog(no_fee_amount(load()), KW)
    assert not passed
    assert any("fee section has no amount" in l for l in fails(lines))


def test_documented_fee_absence_passes():
    passed, lines = check_blog(no_fee_amount(load()), KW, notes=ABSENCES)
    assert passed, fails(lines)
    assert any("fee section has no amount" in l and l.startswith("WARN") for l in lines)


def test_undocumented_review_absence_still_fails():
    passed, lines = check_blog(no_reviews(load()), KW)
    assert not passed
    assert any("no parent review graph" in l for l in fails(lines))


def test_documented_review_absence_passes():
    passed, lines = check_blog(no_reviews(load()), KW, notes=ABSENCES)
    assert passed, fails(lines)
    assert any("no parent review graph" in l and l.startswith("WARN") for l in lines)


def test_absence_without_a_reason_is_ignored():
    """A bare claim is not documentation; the reason is the evidence of research."""
    notes = "## Documented absences\n- Delhi Public School Kalkaji | fee | none\n"
    passed, lines = check_blog(no_fee_amount(load()), KW, notes=notes)
    assert not passed
    assert any("fee section has no amount" in l for l in fails(lines))


def test_absence_for_another_school_does_not_excuse_this_one():
    notes = ABSENCES.replace("Delhi Public School Kalkaji", "Bal Bharati Public School Kalkaji")
    passed, lines = check_blog(no_fee_amount(load()), KW, notes=notes)
    assert not passed
    assert any("fee section has no amount" in l for l in fails(lines))


def test_absence_outside_the_block_is_ignored():
    """Prose elsewhere in notes.md must not excuse anything, or the block means nothing."""
    notes = ("## Other schools with weak evidence\n"
             "- Delhi Public School Kalkaji | fee | Ezyschooling gated the table and no other "
             "directory carries a figure for this school at all\n")
    passed, lines = check_blog(no_fee_amount(load()), KW, notes=notes)
    assert not passed


def test_declared_fee_absence_does_not_excuse_a_published_table_with_no_source():
    """The escape names one failure. A school that did publish a table still needs its
    Source line, so declaring an absence cannot wave the fee rules through as a group."""
    md = load().replace("Source: Delhi Public School Kalkaji Official Website", "", 1)
    passed, lines = check_blog(md, KW, notes=ABSENCES)
    assert not passed
    assert any("fee table has no Source: line" in l for l in fails(lines))


def test_documented_absence_does_not_excuse_other_schools_rules():
    """School 2 keeps failing on its own merits while school 1 is excused."""
    md = no_fee_amount(load()).replace('id="900002"', 'id=""', 1)
    passed, lines = check_blog(md, KW, notes=ABSENCES)
    assert not passed
    assert any("empty btn_admissions id" in l for l in fails(lines))


# --------------------------------------------------------------------------- #
# [read_more_blogs] links have to be built from the school's CMS slug. The skill used to
# tell the writer to build them from the school's name ("/school/[city]/[school-name]"),
# which drops the locality the real slug ends in. All 16 links in the Hyderabad blog
# (Oct 2026) pointed at pages that do not exist -- and because an unknown slug on
# yellowslate.com answers 200 with the homepage rather than 404, not one of them looked
# broken. This is a string comparison against the CMS tab; QC never hits the network.

SLUGS = {"Delhi Public School Kalkaji": "delhi/delhi-public-school-kalkaji-kalkaji",
         "Bal Bharati Public School Kalkaji": "delhi/bal-bharati-public-school-kalkaji-kalkaji"}


def arealess(md):
    """The links the old convention produced: the school's name without its locality."""
    return md.replace("delhi-public-school-kalkaji-kalkaji", "delhi-public-school-kalkaji")


def test_links_built_from_the_cms_slug_pass():
    passed, lines = check_blog(load(), KW, expected_ids=["900001", "900002"], expected_slugs=SLUGS)
    assert passed, fails(lines)


def test_arealess_read_more_links_fail():
    passed, lines = check_blog(arealess(load()), KW, expected_slugs=SLUGS)
    assert not passed
    f = " ".join(fails(lines))
    assert "not built from the CMS slug" in f
    assert "/school/delhi/delhi-public-school-kalkaji" in f


def test_only_the_reviews_link_wrong_still_fails():
    """The two links are built separately, so one can be right while the other is not."""
    md = load().replace('link="/delhi/delhi-public-school-kalkaji-kalkaji-reviews"',
                        'link="/delhi/delhi-public-school-kalkaji-reviews"')
    passed, lines = check_blog(md, KW, expected_slugs=SLUGS)
    assert not passed
    assert any("not built from the CMS slug" in l for l in fails(lines))


def test_another_schools_slug_is_not_this_schools():
    """Both links resolve, so the lowercase-hyphenated rule and the whole-post rule both
    pass. Only the per-school comparison catches a link pointing at the wrong school."""
    md = load().replace('link="/school/delhi/delhi-public-school-kalkaji-kalkaji"',
                        'link="/school/delhi/bal-bharati-public-school-kalkaji-kalkaji"')
    passed, lines = check_blog(md, KW, expected_slugs=SLUGS)
    assert not passed
    assert any("not built from the CMS slug" in l for l in fails(lines))


def test_a_stray_link_fails_even_when_the_h2_name_does_not_match_the_cms():
    """The per-school rule can only fire when the H2 name matches a CMS name. A writer that
    spells the H2 its own way would slip past it with every link dead, so the whole post is
    checked against the run's slugs as well."""
    slugs = {"DPS Kalkaji (Main Branch)": "delhi/delhi-public-school-kalkaji-kalkaji",
             "BBPS Kalkaji": "delhi/bal-bharati-public-school-kalkaji-kalkaji"}
    passed, lines = check_blog(arealess(load()), KW, expected_slugs=slugs)
    assert not passed
    assert any("no school's" in l for l in fails(lines))


def test_links_are_not_checked_when_no_slugs_are_given():
    """A blog QC'd without the CMS tab must not start failing on a rule it has no data for."""
    passed, lines = check_blog(arealess(load()), KW, expected_ids=["900001", "900002"])
    assert passed, fails(lines)
    assert not any("CMS slug" in l for l in lines)


def test_a_trailing_slash_is_not_a_failure():
    md = load().replace('link="/school/delhi/delhi-public-school-kalkaji-kalkaji"',
                        'link="/school/delhi/delhi-public-school-kalkaji-kalkaji/"')
    passed, lines = check_blog(md, KW, expected_slugs=SLUGS)
    assert passed, fails(lines)


def test_slug_links_shape():
    from stages.qc import slug_links
    assert slug_links("hyderabad/kendriya-vidyalaya-kanchan-bagh") == (
        "/school/hyderabad/kendriya-vidyalaya-kanchan-bagh",
        "/hyderabad/kendriya-vidyalaya-kanchan-bagh-reviews")
    assert slug_links("/hyderabad/x-y/") == ("/school/hyderabad/x-y", "/hyderabad/x-y-reviews")


def test_a_documented_absence_does_not_excuse_a_dead_link():
    """The escape names fee and reviews. A dead link is not research, it is a typo."""
    passed, lines = check_blog(arealess(no_fee_amount(load())), KW, notes=ABSENCES,
                               expected_slugs=SLUGS)
    assert not passed
    assert any("not built from the CMS slug" in l for l in fails(lines))


# Three "DAV Public School" rows shared one CMS name in the Bhubaneswar blog (Oct 2026).
# Keyed by name alone, two slugs overwrote each other and their correct links were reported
# as pointing at pages that do not exist, failing a blog whose links were right.
def test_campuses_sharing_a_cms_name_keep_every_slug():
    slugs = {"Delhi Public School Kalkaji": ["delhi/delhi-public-school-kalkaji-kalkaji",
                                             "delhi/delhi-public-school-kalkaji-other"],
             "Bal Bharati Public School Kalkaji": "delhi/bal-bharati-public-school-kalkaji-kalkaji"}
    passed, lines = check_blog(load(), KW, expected_slugs=slugs)
    assert passed, fails(lines)


def test_a_stray_link_still_fails_when_a_name_holds_several_slugs():
    slugs = {"Delhi Public School Kalkaji": ["delhi/delhi-public-school-kalkaji-kalkaji",
                                             "delhi/delhi-public-school-kalkaji-other"],
             "Bal Bharati Public School Kalkaji": "delhi/bal-bharati-public-school-kalkaji-kalkaji"}
    passed, lines = check_blog(arealess(load()), KW, expected_slugs=slugs)
    assert not passed
    assert any("no school's" in l for l in fails(lines))
