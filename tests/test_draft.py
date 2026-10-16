"""Stage 5 turns a QC-passed blog into an unpublished draft in their CMS.

Three things here are easy to get wrong and invisible once published:

  - markdown-it escapes the quotes in [btn_admissions id="9908"] to &quot;, which stops
    their side parsing the shortcode. The blog then goes up with no admission buttons and
    linked_schools comes back 0.
  - the body still points at images/x.jpg on this machine until every one is uploaded and
    swapped. A missed swap is a broken image on their site.
  - their media endpoint takes jpg and png only, and the writer sometimes saves .webp.
"""

import json
import os

import pytest

from clients.blog_base import BlogError
from stages import draft as draft_stage


class FakeBlog:
    """Stands in for clients/blog_api.py. Records what it was asked to do."""

    def __init__(self, linked=0):
        self.uploaded, self.drafts, self.linked = [], [], linked

    def upload_image(self, path, alt=""):
        assert os.path.splitext(path)[1].lower() in (".jpg", ".jpeg", ".png"), path
        self.uploaded.append((os.path.basename(path), alt))
        return {"id": len(self.uploaded), "url": f"https://cdn.example.com/{os.path.basename(path)}"}

    def create_draft(self, blog):
        self.drafts.append(blog)
        return {"id": 51, "uuid": "u-51", "slug": blog["slug"], "status": "draft",
                "edit_url": f"https://cms.example.com/blogs/51/edit",
                "linked_schools": self.linked, "created": True}


META = {"title": "11 Best CBSE Schools in Delhi", "meta_title": "Best CBSE Schools in Delhi",
        "meta_description": "Fees, reviews and admission.", "slug": "best-cbse-schools-in-delhi"}


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
