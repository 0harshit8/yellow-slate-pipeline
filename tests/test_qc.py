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
    md = load().replace('link="/school/delhi/delhi-public-school-kalkaji"', 'link="/school/Delhi/DPS Kalkaji"')
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
