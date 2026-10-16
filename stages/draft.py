"""Stage 5: put a QC-passed blog into Yellow Slate's CMS as an UNPUBLISHED draft.

Where this sits. qc.py is the last stage that only reads; this is the first that writes
anything to their site. It still does not publish: their API has no publish endpoint, and
clients/blog_api.py refuses any reply whose status is not "draft". What comes back is an
edit_url, which opens that draft in their dashboard for a human to read and publish. The
sheet's Status stays at qc_pass and the Live link column carries the edit_url, so "has a
draft" is visible without inventing a status the sheet's validation would reject.

Three things have to happen between blog.md and their API, and each one fails silently:

  1. IMAGES. The body points at images/x.jpg and graphs/y.png on this machine. Every one
     has to be uploaded and its path swapped for the absolute URL their media endpoint
     gives back, or the post goes up with broken images. Their endpoint takes jpg and png
     only, and the writer sometimes saves .webp, so those are converted first.
  2. HTML. Their API stores HTML, and markdown-it escapes a double quote to &quot; - which
     turns [btn_admissions id="9908"] into text their shortcode parser does not recognise.
     The blog would publish with no admission buttons and no school links at all.
  3. THE COUNT. linked_schools in their reply is their own parser's count of the schools it
     linked. Short of the number the blog was built from, some shortcode did not take, and
     that is worth saying before a human publishes it.

Rerunning is safe: POST /blogs is idempotent on the slug, so a retried row updates its own
draft instead of making a second one.
"""

import os
import re
import tempfile

from clients.blog_base import BlogError

# The shortcodes their CMS expands. Both carry double-quoted attributes.
SHORTCODES = ("btn_admissions", "read_more_blogs")
SHORTCODE_IN_HTML = re.compile(r"\[(?:%s)[^\]]*\]" % "|".join(SHORTCODES))

IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
UPLOADABLE = {".jpg", ".jpeg", ".png"}


def to_html(markdown_text):
    """Markdown -> the HTML their API stores, with the shortcodes left intact.

    markdown-it escapes &, < > and " everywhere, which is right for prose and wrong inside a
    shortcode: id=&quot;9908&quot; is not something their parser matches. So the escaping is
    undone within the shortcode brackets only, and prose keeps its own quotes escaped.
    """
    from markdown_it import MarkdownIt

    html = MarkdownIt("commonmark", {"html": True}).enable("table").render(markdown_text)
    return SHORTCODE_IN_HTML.sub(lambda m: m.group(0).replace("&quot;", '"'), html)


def _as_uploadable(path, workdir):
    """Their media endpoint takes jpg and png. Returns a path in one of those, or None."""
    extension = os.path.splitext(path)[1].lower()
    if extension in UPLOADABLE:
        return path
    try:
        from PIL import Image

        out = os.path.join(workdir, os.path.splitext(os.path.basename(path))[0] + ".jpg")
        with Image.open(path) as im:
            im.convert("RGB").save(out, "JPEG", quality=90)
        return out
    except Exception:                       # noqa: BLE001 - one odd image is not a failed blog
        return None


def upload_images(blog, folder, markdown_text):
    """Upload every local image and swap its path for the URL. Returns (text, warnings).

    A local path that is not there, or will not convert, is left in the body and reported:
    one broken image is worth publishing around, and the warning names it so it can be
    fixed. Anything already on http(s) is somebody else's URL and is left alone.
    """
    warnings, done = [], {}
    with tempfile.TemporaryDirectory() as workdir:
        for alt, ref in IMAGE.findall(markdown_text):
            if ref.startswith(("http://", "https://", "data:")) or ref in done:
                continue
            local = os.path.normpath(os.path.join(folder, ref))
            if not os.path.exists(local):
                warnings.append(f"image not on disk, left as a local path: {ref}")
                continue
            sendable = _as_uploadable(local, workdir)
            if not sendable:
                warnings.append(f"image could not be converted to jpg or png: {ref}")
                continue
            try:
                done[ref] = blog.upload_image(sendable, alt=alt)["url"]
            except BlogError as err:
                warnings.append(f"image upload failed, left as a local path: {ref} ({err})")

    for ref, url in done.items():
        markdown_text = markdown_text.replace("(%s)" % ref, "(%s)" % url)
    return markdown_text, warnings


def create(blog, folder, meta, city, area, expect_schools):
    """Upload the images, build the HTML and create the draft. Returns their reply + warnings.

    `expect_schools` is how many schools the blog was built from, which their linked_schools
    is checked against. It is a warning rather than a failure: the draft exists either way,
    and a human opens it next.
    """
    path = os.path.join(folder, "blog.md")
    if not os.path.exists(path):
        raise BlogError(f"No blog.md in {folder}. Run write first.")
    with open(path, encoding="utf-8") as fh:
        body = fh.read()
    if not body.strip():
        raise BlogError(f"{path} is empty.")

    body, warnings = upload_images(blog, folder, body)
    result = blog.create_draft({
        "title": meta["title"],
        "meta_title": meta.get("meta_title", ""),
        "meta_description": meta.get("meta_description", ""),
        "slug": meta["slug"],
        "city": city,
        "area": area,
        "content": to_html(body),
    })

    linked = int(result.get("linked_schools", 0) or 0)
    if expect_schools and linked != expect_schools:
        warnings.append(
            f"their CMS linked {linked} schools, the blog has {expect_schools}. "
            "Check the [btn_admissions] shortcodes in the draft before publishing."
        )
    if not result.get("created", True):
        warnings.append("this slug already had a draft, so the existing one was updated.")

    return {**result, "warnings": warnings}
