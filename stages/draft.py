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
  4. THE SLUG. POST /blogs is idempotent on the slug, and that is worse than it sounds. A
     slug that already has a post returns that post and DISCARDS the body sent with it -
     measured Oct 16, 2026, see clients/blog_api.py. Nothing on their site changes and the
     call still looks like a success. Hit that day with "best-cbse-schools-in-delhi", which
     was already a live 18-school article of theirs.

So rerunning is NOT safe in the way this stage used to claim. A retried row does not update
its own draft; it quietly does nothing, and over 600 blogs that means no correction ever
lands. Two things stop that here:

  - check_slug_is_free looks the slug up on their public site BEFORE anything is sent, so a
    collision with a published post of theirs costs nothing - not even an orphaned image in
    their media bucket, which has no delete call either.
  - a reply carrying created: false is raised as a failure, not logged as a warning. That is
    the only signal an unpublished collision gives, and their API cannot be read back to
    check what is on their side, so it has to be treated as "the body went nowhere".
"""

import os
import re
import tempfile

import config
from clients.blog_base import BlogError

# The shortcodes their CMS expands. Both carry double-quoted attributes.
SHORTCODES = ("btn_admissions", "read_more_blogs")
SHORTCODE_IN_HTML = re.compile(r"\[(?:%s)[^\]]*\]" % "|".join(SHORTCODES))

IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
UPLOADABLE = {".jpg", ".jpeg", ".png"}

# Where a published blog lives on their public site. Measured Oct 16, 2026.
PUBLIC_BLOG = config.SITE + "/blog/%s"
CANONICAL = re.compile(r"""<link[^>]+rel=["']canonical["'][^>]+href=["']([^"']+)""", re.I)
SITE_CHECK_TIMEOUT = 20


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


def _get_page(url):
    """One GET of their public site. Returns the HTML, or None for anything but a clean 200."""
    import requests

    response = requests.get(url, timeout=SITE_CHECK_TIMEOUT,
                            headers={"User-Agent": "yellowslate-pipeline"})
    return response.text if response.status_code == 200 else None


def published_url(slug, fetch=None):
    """The public URL of a LIVE post at this slug, "" when there is none, None when unknown.

    Their pipeline API cannot answer this. Every GET on that base except /health and
    /schools/search is answered 401 INVALID_TOKEN by the CRM's own session auth, so from
    this side /blogs is write-only: a slug cannot be looked up before it is posted to, and
    what was written cannot be read back. Their public site can answer it, with one trap -
    an unknown slug is not a 404 there, it is their homepage served with status 200, byte
    for byte the same page a nonsense slug gets. The one thing that separates a real post
    from that fallback is the canonical link: a post points it at itself, the fallback
    points it at /home.

    None, not "", when the site could not be read, so a caller can report that it did not
    look rather than reporting the slug free. Only a 200 carrying a canonical is judged;
    every other reply is "unknown", which costs a warning and never a wrong refusal.
    """
    url = PUBLIC_BLOG % slug
    try:
        html = (fetch or _get_page)(url)
    except Exception:                       # noqa: BLE001 - unreachable is unknown, not free
        return None
    found = CANONICAL.search(html or "")
    if not found:
        return None
    # Compared on the path, so http/https or a trailing slash on their side cannot read as
    # a different post.
    return url if found.group(1).strip().rstrip("/").endswith("/blog/" + slug) else ""


def check_slug_is_free(slug, fetch=None):
    """Raise before a single byte is sent if this slug is already a live post of theirs.

    This is the whole point of the stage's step 4. Without it the collision is only visible
    in the reply, by which time the POST has landed, every image of this blog is already in
    their media bucket, and the body has been thrown away for nothing.

    Returns the warnings to carry forward, because "I looked and it is free" and "I could
    not look" must not read the same in the run log.
    """
    live = published_url(slug, fetch=fetch)
    if live:
        raise BlogError(
            f"The slug {slug!r} is already a published post on their site: {live}. "
            "POST /blogs is idempotent on the slug, so sending this would hand that live "
            "post back and discard this blog's body instead of making a new post. Nothing "
            "was sent. Change the slug in this blog's meta.json - the Oct 16, 2026 fix was "
            "to add the year - and rerun."
        )
    if live is None:
        return [f"could not read {PUBLIC_BLOG % slug} to check the slug was free before "
                "posting, so this ran on the created:false guard in clients/blog_api.py alone."]
    return []


def create(blog, folder, meta, city, area, expect_schools, fetch=None):
    """Upload the images, build the HTML and create the draft. Returns their reply + warnings.

    `expect_schools` is how many schools the blog was built from, which their linked_schools
    is checked against. It is a warning rather than a failure: the draft exists either way,
    and a human opens it next.

    `fetch` replaces the one GET of their public site that the slug check makes, so a test
    does not need the network.
    """
    path = os.path.join(folder, "blog.md")
    if not os.path.exists(path):
        raise BlogError(f"No blog.md in {folder}. Run write first.")
    with open(path, encoding="utf-8") as fh:
        body = fh.read()
    if not body.strip():
        raise BlogError(f"{path} is empty.")

    # Before the uploads, not after: a slug collision that is caught later still leaves
    # every image of this blog in their media bucket, and there is no delete call for those.
    warnings = check_slug_is_free(meta["slug"], fetch=fetch)

    body, image_warnings = upload_images(blog, folder, body)
    warnings += image_warnings
    result = blog.create_draft({
        "title": meta["title"],
        "meta_title": meta.get("meta_title", ""),
        "meta_description": meta.get("meta_description", ""),
        "slug": meta["slug"],
        "city": city,
        "area": area,
        "content": to_html(body),
    })

    if not result.get("created", True):
        # The slug check above only sees PUBLISHED posts, so an unpublished post of theirs
        # on this slug - or a draft this row already made - gets this far. Either way the
        # body just sent was discarded, so this is a failure and not the "the existing one
        # was updated" it used to be reported as. A corrected blog re-drafted on its own
        # slug would otherwise leave the old body on their site and still read as a success,
        # which over 600 blogs means no correction ever lands.
        raise BlogError(
            f"The slug {meta['slug']!r} already had a post (id {result.get('id')}, status "
            f"{result.get('status')}), so this blog's body was discarded: POST /blogs "
            "returns the existing post and does not update it. Nothing on their site "
            "changed. If that post is this row's own earlier draft, delete it in their "
            f"dashboard and rerun ({result.get('edit_url', 'no edit_url in their reply')}). "
            "If it is one of theirs, change the slug in meta.json and rerun."
        )

    linked = result.get("linked_schools")
    if linked is None:
        warnings.append(
            "their reply carried no linked_schools, so the [btn_admissions] shortcodes "
            "were not counted. Check the admission buttons in the draft by eye."
        )
    elif expect_schools and linked != expect_schools:
        warnings.append(
            f"their CMS linked {linked} schools, the blog has {expect_schools}. "
            "Check the [btn_admissions] shortcodes in the draft before publishing."
        )

    return {**result, "warnings": warnings}
