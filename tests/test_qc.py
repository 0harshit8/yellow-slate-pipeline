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
