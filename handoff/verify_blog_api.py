"""Acceptance checks for blog_api.py. Run this against the live CMS; if it passes, the work is done.

    pip install requests
    set YS_BLOG_BASE_URL=https://.../api        (export on mac/linux)
    set YS_BLOG_API_KEY=...
    python verify_blog_api.py --city Delhi --area Kalkaji

Options:
    --slug SLUG     the test slug to use (default: zz-test-best-schools-in-<area>-<city>)
    --no-image      skip the image upload checks

Standalone on purpose: no Google Sheet, no other credential, nothing from the rest of the pipeline.
It generates its own test image, so no files are needed. It prints the raw response for every call.
Send that output back with the file.
"""

import argparse
import inspect
import json
import os
import struct
import sys
import tempfile
import types
import zlib
from datetime import datetime

# blog_api.py imports clients.blog_base, which lives in the pipeline repo. Stand it up here so the
# same file runs unchanged both inside the pipeline and on its own.
if "clients.blog_base" not in sys.modules:
    class BlogError(RuntimeError):
        pass

    class Blog:
        def create_draft(self, blog):
            raise NotImplementedError

        def upload_image(self, path, alt=""):
            raise NotImplementedError

    pkg = sys.modules.get("clients") or types.ModuleType("clients")
    pkg.__path__ = getattr(pkg, "__path__", [])
    mod = types.ModuleType("clients.blog_base")
    mod.Blog, mod.BlogError = Blog, BlogError
    sys.modules["clients"], sys.modules["clients.blog_base"] = pkg, mod

import requests  # noqa: E402

from clients.blog_base import Blog, BlogError  # noqa: E402
from blog_api import ApiBlog  # noqa: E402

results = []

# The shapes the pipeline calls. Changing these breaks the drop-in even if the API works.
CONTRACT = {"create_draft": ["blog"], "upload_image": ["path", "alt"]}

# A real blog body uses these. They are the things most likely to be mangled in transit.
SHORTCODE = '[btn_admissions id="23817"]'
READ_MORE = '[read_more_blogs link="/delhi/zz-test-school-kalkaji" text="Detailed Information"]'


def body(image_url):
    return f"""Kalkaji sits in the middle of South Delhi's oldest education belt. This is a test
draft created by verify_blog_api.py and can be deleted.

## 1. ZZ Test School Kalkaji

{SHORTCODE}

- [ZZ Test School Kalkaji](https://yellowslate.com/delhi/zz-test-school-kalkaji) is a CBSE school.
- Second intro bullet, with a rupee amount: fees run about Rs 4,250 a month.
- Third intro bullet.

| Detail | Information |
| --- | --- |
| Curriculum | CBSE |
| Know More About School | {READ_MORE} |

![Parent sentiment breakdown for ZZ Test School Kalkaji]({image_url})

#### Conclusion

Test draft. Delete it.
"""


def check(label, fn):
    print("\n--- " + label)
    try:
        ok, note = fn()
    except BlogError as e:
        ok, note = False, "BlogError: {}".format(e)
    except Exception as e:
        ok, note = False, "{}: {}".format(type(e).__name__, e)
    results.append((ok, label, note))
    print("{}  {}  {}".format("PASS" if ok else "FAIL", label, note))


def show(value):
    print(json.dumps(value, indent=2, default=str))
    return value


def test_png(path, size=16):
    """An 8-bit RGB PNG written by hand, so this script needs no image library."""
    raw = b"".join(b"\x00" + bytes([200, 60, 60] * size) for _ in range(size))

    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw))
           + chunk(b"IEND", b""))
    with open(path, "wb") as fh:
        fh.write(png)
    return path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--city", required=True)
    p.add_argument("--area", required=True)
    p.add_argument("--slug", default=None)
    p.add_argument("--no-image", action="store_true")
    args = p.parse_args()

    for var in ("YS_BLOG_BASE_URL", "YS_BLOG_API_KEY"):
        if not os.environ.get(var):
            sys.exit(var + " is not set.")

    blog = ApiBlog()
    slug = args.slug or "zz-test-best-schools-in-{}-{}".format(
        args.area.lower().replace(" ", "-"), args.city.lower().replace(" ", "-"))
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    state = {"image_url": "graphs/zz-test.png", "draft": None}

    def c0():
        """The drop-in contract. An API that works but a signature that drifted is still broken."""
        problems = []
        if not issubclass(ApiBlog, Blog):
            problems.append("ApiBlog no longer subclasses Blog. Keep 'from clients.blog_base import Blog, BlogError'.")
        for method, want in CONTRACT.items():
            fn = getattr(ApiBlog, method, None)
            if fn is None:
                problems.append(method + "() is missing")
                continue
            got = [n for n in inspect.signature(fn).parameters if n != "self"]
            if got != want:
                problems.append("{}({}) should be {}({})".format(
                    method, ", ".join(got), method, ", ".join(want)))
        if problems:
            return False, " | ".join(problems)
        return True, "class and both signatures match the contract"

    def c7():
        """Every failure has to surface as BlogError. Anything else stops a whole batch."""
        real = os.environ["YS_BLOG_BASE_URL"]
        os.environ["YS_BLOG_BASE_URL"] = "http://127.0.0.1:9"  # nothing listening
        try:
            dead = ApiBlog()
            dead.create_draft({"title": "x", "meta_title": "x", "meta_description": "x",
                               "slug": "zz-unreachable-test", "city": args.city,
                               "area": args.area, "content": "x"})
            return False, "an unreachable API raised nothing at all. It must raise BlogError."
        except BlogError as e:
            return True, "wrapped as BlogError: " + str(e)[:120]
        except Exception as e:
            return False, ("an unreachable API raised {}, not BlogError. "
                           "Wrap every failure in BlogError or one bad blog kills the batch."
                           .format(type(e).__name__))
        finally:
            os.environ["YS_BLOG_BASE_URL"] = real

    def c1():
        path = test_png(os.path.join(tempfile.gettempdir(), "zz-test-" + stamp + ".png"))
        out = show(blog.upload_image(path, alt="ZZ test image"))
        if not isinstance(out, dict) or not str(out.get("url", "")).strip():
            return False, "expected a dict with a 'url', got {!r}".format(out)
        url = out["url"]
        if not url.startswith("http"):
            return False, "url is not absolute: {!r}. A relative path breaks the blog body.".format(url)
        state["image_url"] = url
        return True, url

    def c2():
        r = requests.get(state["image_url"], timeout=30)
        ctype = r.headers.get("Content-Type", "")
        if not r.ok:
            return False, "the uploaded image URL returns {}".format(r.status_code)
        if "image" not in ctype:
            return False, "the URL serves {!r}, not an image".format(ctype)
        return True, "{}, {}, {} bytes".format(r.status_code, ctype, len(r.content))

    def c3():
        payload = {
            "title": "10 Best Schools in {}, {} 2026-27: Fees, Reviews and Admission".format(args.area, args.city),
            "meta_title": "10 Best Schools in {}, {} 2026-27: Fees and Reviews".format(args.area, args.city),
            "meta_description": "Compare the 10 best schools in {}, {} for 2026-27.".format(args.area, args.city),
            "slug": slug,
            "city": args.city,
            "area": args.area,
            "content": body(state["image_url"]),
        }
        out = show(blog.create_draft(payload))
        if not isinstance(out, dict):
            return False, "expected a dict, got {}".format(type(out).__name__)
        for field in ("id", "slug", "status", "edit_url"):
            if field not in out:
                return False, "missing '{}'".format(field)
        if not str(out["id"]).strip().isdigit():
            return False, "id is not numeric: {!r}".format(out["id"])
        state["draft"] = out
        return True, "id=" + str(out["id"])

    def c4():
        d = state["draft"]
        if not d:
            return False, "skipped, create_draft did not return a draft"
        if d["slug"] != slug:
            return False, ("the CMS changed the slug: sent {!r}, got {!r}. "
                           "The blog URL must be the one we send.".format(slug, d["slug"]))
        return True, "slug kept as sent: " + slug

    def c5():
        d = state["draft"]
        if not d:
            return False, "skipped, create_draft did not return a draft"
        status = str(d.get("status", "")).lower()
        if status in ("draft", "unpublished", "pending", "0", "false"):
            return True, "status={!r}".format(d["status"])
        return False, "status={!r}. It must come back unpublished, not live.".format(d["status"])

    def c6():
        d = state["draft"]
        if not d:
            return False, "skipped, create_draft did not return a draft"
        again = show(blog.create_draft({
            "title": "resend", "meta_title": "resend", "meta_description": "resend",
            "slug": slug, "city": args.city, "area": args.area,
            "content": body(state["image_url"]),
        }))
        if str(again.get("id")) == str(d["id"]):
            return True, "same id back: {}, no duplicate".format(again["id"])
        return False, ("a second draft was created on the same slug (id {} vs {}). "
                       "Failed rows get retried, so this would duplicate blogs.".format(again.get("id"), d["id"]))

    check("0. the file still matches the contract", c0)
    if args.no_image:
        print("\n--no-image: skipped checks 1-2")
    else:
        check("1. image uploads and returns an absolute URL", c1)
        check("2. the uploaded image URL actually serves an image", c2)
    check("3. draft is created and returns id, slug, status, edit_url", c3)
    check("4. the slug is kept exactly as sent", c4)
    check("5. the draft comes back unpublished", c5)
    check("6. re-sending the same slug does not duplicate", c6)
    check("7. failures come back as BlogError", c7)

    failed = [r for r in results if not r[0]]
    print("\n" + "=" * 60)
    for ok, label, note in results:
        print("{}  {}".format("PASS" if ok else "FAIL", label))
    if state["draft"]:
        print("\nTest draft to delete afterwards: id {}, slug {!r}".format(state["draft"]["id"], slug))
        print("Open " + (state["draft"].get("edit_url") or "(no edit_url returned)") + " and confirm BY EYE:")
        print("  - the shortcode is intact and unescaped: " + SHORTCODE)
        print("  - the read_more_blogs shortcode is intact: " + READ_MORE)
        print("  - the markdown table renders as a table")
        print("  - the image shows")
        print("  - the rupee amount and the apostrophe in \"Delhi's\" are not mangled")
    print("\n{}/{} passed".format(len(results) - len(failed), len(results)))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
