"""Real Yellow Slate blog client. Fill in the two TODOs, then run verify_blog_api.py.

Drops back into the pipeline as clients/blog_api.py. Only this file changes.

Contract, in full:

    create_draft(blog)
        blog = {"title", "meta_title", "meta_description", "slug", "city", "area", "content"}
        -> {"id": int, "slug": str, "status": str, "edit_url": str}
        Creates an UNPUBLISHED draft. Never publishes.
        Idempotent on slug: a slug that already exists returns that draft, never a second one.

    upload_image(path, alt="")
        -> {"url": str}   absolute URL, usable inside the blog body
        One local .jpg or .png at a time.

Order of use, per blog: every image is uploaded first, the returned URLs are substituted into
the body, then the draft is created. So upload_image must work for create_draft to be useful.
"""

import mimetypes
import os

import requests

from clients.blog_base import Blog, BlogError

TIMEOUT = 60


def _base_url():
    url = os.environ.get("YS_BLOG_BASE_URL", "").strip().rstrip("/")
    if not url:
        raise BlogError("No YS_BLOG_BASE_URL set.")
    return url


def _key():
    key = os.environ.get("YS_BLOG_API_KEY", "").strip()
    if not key:
        raise BlogError("No YS_BLOG_API_KEY set.")
    return key


def _headers(json_body=True):
    # TODO: confirm the auth header the CMS expects. Same key as the schools API, or a different one?
    h = {"Authorization": f"Bearer {_key()}"}
    if json_body:
        h["Content-Type"] = "application/json"
    return h


def _call(method, path, json_body=True, **kwargs):
    """One place for every request, so errors and timeouts behave the same everywhere."""
    r = requests.request(method, f"{_base_url()}/{path.lstrip('/')}",
                         headers=_headers(json_body), timeout=TIMEOUT, **kwargs)
    if r.status_code in (401, 403):
        raise BlogError(f"Blog API rejected the key ({r.status_code}).")
    if not r.ok:
        raise BlogError(f"Blog API error {r.status_code} on {method} {path}: {r.text[:400]}")
    try:
        return r.json()
    except ValueError:
        raise BlogError(f"Blog API returned non-JSON on {method} {path}: {r.text[:200]}")


class ApiBlog(Blog):
    def create_draft(self, blog):
        # TODO: create the draft and map the response to {"id", "slug", "status", "edit_url"}.
        #
        #   data = _call("POST", "blogs", json={
        #       "title": blog["title"],
        #       "meta_title": blog["meta_title"],
        #       "meta_description": blog["meta_description"],
        #       "slug": blog["slug"],            # must be kept as given, not regenerated
        #       "city": blog["city"],
        #       "area": blog.get("area", ""),
        #       "content": blog["content"],      # format TBC: html or markdown. See README question 1.
        #       "status": "draft",               # must NOT publish
        #   })
        #   new = data.get("data") or data
        #   return {
        #       "id": int(new["id"]),
        #       "slug": new["slug"],
        #       "status": new.get("status", "draft"),
        #       "edit_url": new.get("edit_url", ""),
        #   }
        #
        # If the slug already exists: return that existing draft rather than creating a second one.
        # 600 blogs get written in batches and failed rows are retried, so this will happen.
        raise BlogError("create_draft not implemented yet")

    def upload_image(self, path, alt=""):
        # TODO: upload one file and return its absolute URL.
        #
        #   ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        #   with open(path, "rb") as fh:
        #       data = _call("POST", "media", json_body=False,
        #                    files={"file": (os.path.basename(path), fh, ctype)},
        #                    data={"alt": alt})
        #   new = data.get("data") or data
        #   return {"url": new["url"]}
        #
        # The URL must be absolute. A relative path breaks the blog body.
        raise BlogError("upload_image not implemented yet")
