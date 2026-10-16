"""Real Yellow Slate blog client. Live since their handover on Oct 10, 2026.

Two endpoints, same base URL and same key as the schools API:
  POST /media   multipart, jpg or png, 5 MB a file, 6 MB a body
  POST /blogs   201 when new, 200 with created: false when the slug already exists

Both are drafts only. There is no publish endpoint, so the last click stays manual:
create_draft returns edit_url, which opens that draft in their dashboard.

Order of use, per blog: every image is uploaded first, the returned URLs are substituted
into the body, then the draft is created.

Content is HTML, and their shortcodes survive it. A body carrying [btn_admissions id="7713"]
comes back with linked_schools: 1, so their side parses the shortcode and links the school.
That count is returned from create_draft as "linked_schools" so qc.py can check it against
the number of schools the blog was built from.
"""

import mimetypes
import os

from clients.blog_base import Blog, BlogError
from clients import ys_http

MAX_IMAGE_BYTES = 5 * 1024 * 1024
ALLOWED_IMAGE = {".jpg", ".jpeg", ".png"}

# Their documented ceilings. Checked here so a 600-blog batch fails on the row, with the
# field named, instead of on a 400 from their side that says only "invalid input".
LIMITS = {"title": 255, "meta_title": 255, "meta_description": 1000, "slug": 200}
MAX_CONTENT_BYTES = 5 * 1024 * 1024
SLUG_SHAPE = "abcdefghijklmnopqrstuvwxyz0123456789-"


class ApiBlog(Blog):
    def create_draft(self, blog):
        """Returns {"id", "uuid", "slug", "status", "edit_url", "linked_schools", "created"}."""
        payload = {
            "title": blog["title"],
            "meta_title": blog.get("meta_title", ""),
            "meta_description": blog.get("meta_description", ""),
            "slug": blog["slug"],          # kept exactly as sent, never regenerated on their side
            "city": blog["city"],
            "area": blog.get("area", ""),
            "content": blog["content"],    # HTML, shortcodes included
        }
        _check(payload)

        try:
            body = ys_http.call("POST", "blogs", json_body=payload)
        except ys_http.UnknownPlace as exc:
            raise BlogError(str(exc)) from exc
        except ys_http.YSApiError as exc:
            raise BlogError(str(exc)) from exc

        new = ys_http.unwrap(body) or {}
        if "id" not in new:
            raise BlogError(f"Draft create returned no id for slug {blog['slug']!r}: {body}")

        status = new.get("status", "draft")
        made = bool(body.get("created", True)) if isinstance(body, dict) else True
        if status != "draft":
            # Two very different things land here, and the difference decides what to do next.
            #
            # created: false means the slug was already taken, so this reply is somebody
            # else's post handed back - a LIVE one, if status is published. Nothing new was
            # made, but their endpoint is idempotent on the slug and their docs do not say
            # whether it rewrites that post's content first, so a collision is worth naming
            # loudly rather than reporting as "their API published my draft".
            #
            # created: true means they really did publish a fresh post, which breaks the
            # promise this whole stage rests on. Stop either way.
            if not made:
                raise BlogError(
                    f"The slug {blog['slug']!r} already belongs to a {status} post "
                    f"(id {new.get('id')}). Nothing new was created. Their endpoint is "
                    "idempotent on the slug, so pick a different slug rather than retrying, "
                    "and check that live post: their docs do not say whether this call "
                    "rewrote its content."
                )
            raise BlogError(
                f"Expected status 'draft' for {blog['slug']!r} but their API created it as "
                f"{status!r}. Stopping: publishing is meant to stay manual."
            )

        return {
            "id": int(new["id"]),
            "uuid": new.get("uuid", ""),
            "slug": new.get("slug", blog["slug"]),
            "status": status,
            "edit_url": new.get("edit_url", ""),
            "linked_schools": int(new.get("linked_schools", 0) or 0),
            # False means this slug already had a draft, so a retried row did not double up
            "created": made,
        }

    def upload_image(self, path, alt=""):
        """Upload one local .jpg or .png. Returns {"id", "url"} with an absolute URL."""
        extension = os.path.splitext(path)[1].lower()
        if extension not in ALLOWED_IMAGE:
            raise BlogError(f"{os.path.basename(path)}: only jpg and png are accepted, not {extension}.")
        if not os.path.exists(path):
            raise BlogError(f"No such image: {path}")

        size = os.path.getsize(path)
        if size > MAX_IMAGE_BYTES:
            raise BlogError(
                f"{os.path.basename(path)} is {size / 1024 / 1024:.1f} MB. Their limit is 5 MB."
            )

        content_type = mimetypes.guess_type(path)[0] or "image/png"
        try:
            with open(path, "rb") as handle:
                body = ys_http.call("POST", "media",
                                    files={"file": (os.path.basename(path), handle, content_type)},
                                    data={"alt": alt})
        except ys_http.YSApiError as exc:
            raise BlogError(str(exc)) from exc

        new = ys_http.unwrap(body) or {}
        url = new.get("url", "")
        if not url.startswith("http"):
            # A relative path silently breaks every image in the blog body, so refuse it here.
            raise BlogError(f"Upload of {os.path.basename(path)} returned no absolute URL: {body}")
        return {"id": new.get("id", ""), "url": url}


def _check(payload):
    """Catch what their 400 would catch, but name the field and the row."""
    for field, limit in LIMITS.items():
        value = payload.get(field) or ""
        if len(value) > limit:
            raise BlogError(f"{field} is {len(value)} characters, their limit is {limit}: {value[:60]}...")

    if not payload["title"].strip():
        raise BlogError("A draft needs a title.")
    if not payload["content"].strip():
        raise BlogError(f"Draft {payload['slug']!r} has no content.")

    # Measured Oct 10, 2026: their API rejects an empty meta_title or meta_description with a
    # 400 that names neither field. Their docs give only the length ceilings, not that both are
    # required. qc.py already checks these, so a hit here means a row reached publish past QC.
    for field in ("meta_title", "meta_description"):
        if not (payload.get(field) or "").strip():
            raise BlogError(
                f"Draft {payload['slug']!r} has an empty {field}. Their API requires both "
                "meta_title and meta_description, and rejects the post without saying which."
            )

    slug = payload["slug"]
    bad = sorted({c for c in slug if c not in SLUG_SHAPE})
    if not slug or bad:
        raise BlogError(
            f"Slug {slug!r} must be lowercase letters, digits and hyphens only. Not allowed: {''.join(bad)}"
        )

    size = len(payload["content"].encode("utf-8"))
    if size > MAX_CONTENT_BYTES:
        raise BlogError(f"Content is {size / 1024 / 1024:.1f} MB, their limit is 5 MB.")
