"""Stage 5 turns a QC-passed blog into an unpublished draft in their CMS.

Three things here are easy to get wrong and invisible once published:

  - markdown-it escapes the quotes in [btn_admissions id="9908"] to &quot;, which stops
    their side parsing the shortcode. The blog then goes up with no admission buttons and
    linked_schools comes back 0.
  - the body still points at images/x.jpg on this machine until every one is uploaded and
    swapped. A missed swap is a broken image on their site.
  - their media endpoint takes jpg and png only, and the writer sometimes saves .webp.
  - the slug may already belong to a post of theirs, in which case POST /blogs hands that
    post back and discards this blog's body - a call that looks like a success and changed
    nothing. Measured Oct 16, 2026; see clients/blog_api.py.
"""

import json
import os

import pytest

from clients.blog_base import BlogError
from stages import draft as draft_stage


class FakeBlog:
    """Stands in for clients/blog_api.py. Records what it was asked to do.

    `created=False` is their reply to a slug that already has a post: the same id back, and
    no linked_schools at all, because only their create branch parses the shortcodes.
    """

    def __init__(self, linked=0, created=True):
        self.uploaded, self.drafts, self.linked, self.created = [], [], linked, created

    def upload_image(self, path, alt=""):
        assert os.path.splitext(path)[1].lower() in (".jpg", ".jpeg", ".png"), path
        self.uploaded.append((os.path.basename(path), alt))
        return {"id": len(self.uploaded), "url": f"https://cdn.example.com/{os.path.basename(path)}"}

    def create_draft(self, blog):
        self.drafts.append(blog)
        return {"id": 51, "uuid": "u-51", "slug": blog["slug"], "status": "draft",
                "edit_url": f"https://cms.example.com/blogs/51/edit",
                "linked_schools": self.linked if self.created else None,
                "created": self.created}


META = {"title": "11 Best CBSE Schools in Delhi", "meta_title": "Best CBSE Schools in Delhi",
        "meta_description": "Fees, reviews and admission.", "slug": "best-cbse-schools-in-delhi"}

# What their public site serves: a real post points its canonical at itself, and a slug with
# no post gets the homepage at status 200 with the canonical pointing at /home.
LIVE_PAGE = '<html><head><link rel="canonical" href="https://yellowslate.com/blog/%s"/></head></html>'
FREE_PAGE = '<html><head><link rel="canonical" href="https://yellowslate.com/home"/></head></html>'


@pytest.fixture(autouse=True)
def never_touch_their_site(monkeypatch):
    """No test here may reach yellowslate.com.

    META's slug is a post Yellow Slate really has live, so without this the slug guard
    would refuse every draft in this file - and a suite that depends on a third party's
    site is a suite that fails on a train. Tests that care about the guard pass their own
    `fetch` instead, which goes round this.
    """
    monkeypatch.setattr(draft_stage, "_get_page", lambda url: FREE_PAGE)


@pytest.fixture
def folder(tmp_path):
    (tmp_path / "images").mkdir()
    (tmp_path / "graphs").mkdir()
    from PIL import Image
    Image.new("RGB", (4, 4), "white").save(tmp_path / "images" / "a-school.jpg")
    Image.new("RGB", (4, 4), "white").save(tmp_path / "graphs" / "a-school.png")
    (tmp_path / "meta.json").write_text(json.dumps(META), encoding="utf-8")
    return str(tmp_path)


def write_md(folder, body):
    path = os.path.join(folder, "blog.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)
    return path


# ---- HTML conversion ----------------------------------------------------------------

def test_shortcode_quotes_survive_the_html_conversion():
    """markdown-it escapes " to &quot;, and their shortcode parser then sees nothing."""
    html = draft_stage.to_html('Intro.\n\n[btn_admissions id="9908"]\n')
    assert '[btn_admissions id="9908"]' in html
    assert "&quot;" not in html


def test_read_more_blogs_quotes_survive_too():
    html = draft_stage.to_html('[read_more_blogs link="/delhi/x-reviews" text="Read Parent Reviews"]')
    assert '[read_more_blogs link="/delhi/x-reviews" text="Read Parent Reviews"]' in html


def test_a_quote_in_ordinary_prose_is_still_escaped():
    """Only shortcodes are unescaped. Prose must keep its HTML escaping."""
    html = draft_stage.to_html('She said "hello" to the class.')
    assert "&quot;hello&quot;" in html


def test_fee_tables_become_html_tables():
    html = draft_stage.to_html("| Class | Fee |\n| --- | --- |\n| Nursery | 1,55,625 |\n")
    assert "<table>" in html and "<td>Nursery</td>" in html


# ---- images -------------------------------------------------------------------------

def test_every_local_image_is_uploaded_and_swapped(folder):
    write_md(folder, "![A School](images/a-school.jpg)\n\n![Graph](graphs/a-school.png)\n")
    blog = FakeBlog(linked=1)
    out = draft_stage.create(blog, folder, META, "Delhi", "Delhi", expect_schools=1)
    body = blog.drafts[0]["content"]
    assert "images/a-school.jpg" not in body and "graphs/a-school.png" not in body
    assert "https://cdn.example.com/a-school.jpg" in body
    assert len(blog.uploaded) == 2
    assert out["edit_url"].endswith("/edit")


def test_the_alt_text_goes_up_with_the_image(folder):
    write_md(folder, "![Campus of A School](images/a-school.jpg)\n")
    blog = FakeBlog(linked=1)
    draft_stage.create(blog, folder, META, "Delhi", "Delhi", expect_schools=1)
    assert blog.uploaded[0][1] == "Campus of A School"


def test_a_webp_is_converted_because_their_api_takes_jpg_and_png_only(folder):
    from PIL import Image
    Image.new("RGB", (4, 4), "white").save(os.path.join(folder, "images", "b-school.webp"))
    write_md(folder, "![B School](images/b-school.webp)\n")
    blog = FakeBlog(linked=1)
    draft_stage.create(blog, folder, META, "Delhi", "Delhi", expect_schools=1)
    assert blog.uploaded[0][0].endswith(".jpg")
    assert ".webp" not in blog.drafts[0]["content"]


def test_a_missing_image_is_reported_and_does_not_stop_the_draft(folder):
    write_md(folder, "![A School](images/a-school.jpg)\n\n![Gone](images/gone.jpg)\n")
    blog = FakeBlog(linked=1)
    out = draft_stage.create(blog, folder, META, "Delhi", "Delhi", expect_schools=1)
    assert any("gone.jpg" in w for w in out["warnings"])
    assert len(blog.uploaded) == 1


def test_an_image_already_on_the_web_is_left_alone(folder):
    write_md(folder, "![Remote](https://example.com/x.jpg)\n")
    blog = FakeBlog(linked=1)
    draft_stage.create(blog, folder, META, "Delhi", "Delhi", expect_schools=1)
    assert blog.uploaded == []
    assert "https://example.com/x.jpg" in blog.drafts[0]["content"]


# ---- what the draft carries ---------------------------------------------------------

def test_the_draft_carries_the_meta_and_the_place(folder):
    write_md(folder, "Intro.\n")
    blog = FakeBlog(linked=0)
    draft_stage.create(blog, folder, META, "Delhi", "Dwarka", expect_schools=0)
    sent = blog.drafts[0]
    assert sent["title"] == META["title"]
    assert sent["meta_description"] == META["meta_description"]
    assert sent["slug"] == META["slug"]
    assert (sent["city"], sent["area"]) == ("Delhi", "Dwarka")


def test_a_shortcode_their_side_did_not_link_is_warned_about(folder):
    """linked_schools is their parser's own count. Short of the blog's, buttons are missing."""
    write_md(folder, '[btn_admissions id="9908"]\n\n[btn_admissions id="8227"]\n')
    blog = FakeBlog(linked=1)
    out = draft_stage.create(blog, folder, META, "Delhi", "Delhi", expect_schools=2)
    assert any("linked 1" in w and "2" in w for w in out["warnings"])


def test_a_blog_with_no_markdown_file_is_refused(folder):
    with pytest.raises(BlogError):
        draft_stage.create(FakeBlog(), folder, META, "Delhi", "Delhi", expect_schools=0)


# ---- the slug guard -----------------------------------------------------------------
#
# Their pipeline API is write-only: every GET on it but /health and /schools/search is
# answered 401 by the CRM's session auth. So a slug cannot be looked up through the API
# before posting to it, and their public site is the only place that can answer.

def test_a_published_post_is_recognised_by_its_canonical_link():
    slug = "best-schools-in-kalkaji-delhi"
    found = draft_stage.published_url(slug, fetch=lambda url: LIVE_PAGE % slug)
    assert found == "https://yellowslate.com/blog/" + slug


def test_the_homepage_fallback_reads_as_a_free_slug():
    """A slug with no post is not a 404 on their site, it is the homepage at status 200.
    Anything reading the status code would call every slug in the world taken."""
    assert draft_stage.published_url("no-such-blog-9981", fetch=lambda url: FREE_PAGE) == ""


def test_a_site_that_cannot_be_read_is_unknown_rather_than_free():
    """"free" here would post on the strength of a check that never actually happened."""
    def unreachable(url):
        raise OSError("connection reset by peer")

    assert draft_stage.published_url("a-slug", fetch=unreachable) is None
    assert draft_stage.published_url("a-slug", fetch=lambda url: None) is None
    assert draft_stage.published_url("a-slug", fetch=lambda url: "<html>no canonical</html>") is None


def test_the_canonical_is_compared_on_the_path():
    """So their canonical switching to http, or growing a trailing slash, does not read as a
    different post and silently turn the guard off."""
    page = '<link rel="canonical" href="http://yellowslate.com/blog/a-slug/">'
    assert draft_stage.published_url("a-slug", fetch=lambda url: page)


def test_a_slug_that_only_shares_a_prefix_is_not_a_collision():
    """Re-slugging was the Oct 16, 2026 fix: "...-in-delhi" was live, "...-in-delhi-2026"
    was free. If a prefix counted as a collision there would have been no way out."""
    page = LIVE_PAGE % "best-cbse-schools-in-delhi"
    assert draft_stage.published_url("best-cbse-schools-in-delhi-2026",
                                     fetch=lambda url: page) == ""


def test_a_live_post_refuses_before_a_single_image_is_uploaded(folder):
    """The uploads happen first, and their media endpoint has no delete call either, so a
    collision caught after them leaves this blog's images in their bucket for good."""
    write_md(folder, "![A School](images/a-school.jpg)\n")
    blog = FakeBlog(linked=1)
    with pytest.raises(BlogError) as caught:
        draft_stage.create(blog, folder, META, "Delhi", "Delhi", expect_schools=1,
                           fetch=lambda url: LIVE_PAGE % META["slug"])
    assert "published post" in str(caught.value)
    assert blog.uploaded == [] and blog.drafts == []


def test_a_slug_check_that_could_not_run_is_said_out_loud_but_does_not_stop_the_blog(folder):
    """Their site being down must not stall a batch of 600. The reply still carries the
    created:false guard. What the run log must not do is look like the slug was checked."""
    write_md(folder, "Intro.\n")
    blog = FakeBlog(linked=0)
    out = draft_stage.create(blog, folder, META, "Delhi", "Delhi", expect_schools=0,
                             fetch=lambda url: None)
    assert any("could not read" in w for w in out["warnings"])
    assert blog.drafts, "an unreadable site should not have stopped the draft"


# ---- a slug that already has a post -------------------------------------------------

def test_a_repeat_post_is_a_failure_because_the_body_is_discarded(folder):
    """POST /blogs returns the post that already holds the slug and throws the body away.

    This used to be a warning that read as success, which is the worse half of the problem:
    a blog corrected and re-drafted on its own slug left the old body on their site, and
    the sheet recorded a draft. Across 600 blogs no correction would ever have landed.
    """
    write_md(folder, "Intro.\n")
    blog = FakeBlog(created=False)
    with pytest.raises(BlogError) as caught:
        draft_stage.create(blog, folder, META, "Delhi", "Delhi", expect_schools=0,
                           fetch=lambda url: FREE_PAGE)
    message = str(caught.value)
    assert "discarded" in message
    # The edit_url has to be in the message: deleting that draft is how the rerun works.
    assert "/edit" in message


def test_a_reply_with_no_count_is_not_read_as_zero_schools_linked(folder):
    """Their API leaves linked_schools out rather than sending 0. Read as 0, it warned
    "linked 0 schools, the blog has 11" about drafts that were perfectly fine."""
    write_md(folder, '[btn_admissions id="9908"]\n')
    blog = FakeBlog(linked=None)
    out = draft_stage.create(blog, folder, META, "Delhi", "Delhi", expect_schools=1,
                             fetch=lambda url: FREE_PAGE)
    assert any("no linked_schools" in w for w in out["warnings"])
    assert not any("linked 0" in w for w in out["warnings"])


def test_not_counted_and_zero_stay_different_in_the_client():
    """clients/blog_api.py reads their reply. Only one of these is a broken shortcode."""
    from clients.blog_api import _count

    assert _count({"id": 1}) is None, "an absent count must not collapse into 0"
    assert _count({"id": 1, "linked_schools": None}) is None
    assert _count({"id": 1, "linked_schools": 0}) == 0
    assert _count({"id": 1, "linked_schools": "3"}) == 3
    assert _count({"id": 1, "linked_schools": "lots"}) is None
