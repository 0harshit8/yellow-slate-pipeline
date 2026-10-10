"""Acceptance checks for cms_api.py. Run this against the live CMS; if it passes, the work is done.

    pip install requests
    set YS_CMS_BASE_URL=https://.../api        (export on mac/linux)
    set YS_CMS_API_KEY=...
    python verify_cms_api.py --city Delhi --area Kalkaji --known "Delhi Public School Kalkaji"

Options:
    --no-create    run only the read-only checks
    --short        the short form to test loose matching with (default: first word + area)

Standalone on purpose: no Google Sheet, no other credential, nothing from the rest of the pipeline.
It prints the raw response for every call. Send that output back with the file.
"""

import argparse
import inspect
import json
import os
import sys
import types
from datetime import datetime

# cms_api.py imports clients.cms_base, which lives in the pipeline repo. Stand it up here so the
# same file runs unchanged both inside the pipeline and on its own.
if "clients.cms_base" not in sys.modules:
    class CMSError(RuntimeError):
        pass

    class CMS:
        def search_school(self, name, city, area):
            raise NotImplementedError

        def create_school(self, name, city, area, email):
            raise NotImplementedError

    pkg = types.ModuleType("clients")
    pkg.__path__ = []
    mod = types.ModuleType("clients.cms_base")
    mod.CMS, mod.CMSError = CMS, CMSError
    sys.modules["clients"], sys.modules["clients.cms_base"] = pkg, mod

from clients.cms_base import CMS, CMSError  # noqa: E402
from cms_api import ApiCMS  # noqa: E402

results = []

# The shapes the pipeline calls. Changing these breaks the drop-in even if the API works.
CONTRACT = {"search_school": ["name", "city", "area"],
            "create_school": ["name", "city", "area", "email"]}


def check(label, fn):
    print(f"\n--- {label}")
    try:
        ok, note = fn()
    except CMSError as e:
        ok, note = False, f"CMSError: {e}"
    except Exception as e:
        ok, note = False, f"{type(e).__name__}: {e}"
    results.append((ok, label, note))
    print(f"{'PASS' if ok else 'FAIL'}  {label}  {note}")


def show(value):
    print(json.dumps(value, indent=2, default=str))
    return value


def shape_ok(hit):
    """A result is usable only if it has an integer-ish id and a non-empty slug."""
    if not isinstance(hit, dict):
        return False, f"expected a dict, got {type(hit).__name__}"
    for field in ("id", "name", "slug"):
        if field not in hit:
            return False, f"missing '{field}'"
    if not str(hit["id"]).strip().isdigit():
        return False, f"id is not numeric: {hit['id']!r}"
    if not str(hit["slug"]).strip():
        return False, "slug is empty"
    if "/" not in str(hit["slug"]):
        return False, f"slug is not 'city/school-name-area': {hit['slug']!r}"
    return True, f"id={hit['id']} slug={hit['slug']}"


def email_for(name):
    return "".join(c for c in name.lower() if c.isalnum()) + "@gmail.com"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--city", required=True)
    p.add_argument("--area", required=True)
    p.add_argument("--known", required=True, help="a school that already exists in this city + area")
    p.add_argument("--short", default=None, help="short form of --known, to test loose matching")
    p.add_argument("--no-create", action="store_true")
    args = p.parse_args()

    for var in ("YS_CMS_BASE_URL", "YS_CMS_API_KEY"):
        if not os.environ.get(var):
            sys.exit(f"{var} is not set.")

    cms = ApiCMS()
    short = args.short or f"{args.known.split()[0]} {args.area}"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    test_name = f"ZZ Test School {stamp} {args.area}"
    created = {}

    def c0():
        """The drop-in contract. An API that works but a signature that drifted is still broken."""
        problems = []
        if not issubclass(ApiCMS, CMS):
            problems.append("ApiCMS no longer subclasses CMS. Keep 'from clients.cms_base import CMS, CMSError'.")
        for method, want in CONTRACT.items():
            fn = getattr(ApiCMS, method, None)
            if fn is None:
                problems.append(f"{method}() is missing")
                continue
            got = [n for n in inspect.signature(fn).parameters if n != "self"]
            if got != want:
                problems.append(f"{method}({', '.join(got)}) should be {method}({', '.join(want)})")
        if problems:
            return False, " | ".join(problems)
        return True, "class and both signatures match the contract"

    def c1():
        hit = show(cms.search_school(args.known, args.city, args.area))
        if hit is None:
            return False, f"{args.known!r} was not found. Pick a school that definitely exists, or the search is broken."
        return shape_ok(hit)

    def c2():
        hit = show(cms.search_school(short, args.city, args.area))
        if hit is None:
            return False, f"loose match failed: {short!r} did not find {args.known!r}. Note it as a limitation if the API only matches exactly."
        return shape_ok(hit)

    def c3():
        hit = show(cms.search_school("Qzxv Nonexistent Academy", args.city, args.area))
        if hit is None:
            return True, "returned None, correct"
        return False, f"returned a match for a made-up school: {hit}"

    def c4():
        new = show(cms.create_school(test_name, args.city, args.area, email_for(test_name)))
        ok, note = shape_ok(new)
        if ok:
            created.update(new)
        return ok, note

    def c5():
        if not created:
            return False, "skipped, create did not return an id"
        hit = show(cms.search_school(test_name, args.city, args.area))
        if hit is None:
            return False, "the school just created cannot be found by search. Reruns would duplicate it."
        if str(hit["id"]) != str(created["id"]):
            return False, f"search returned id {hit['id']}, create returned {created['id']}"
        return True, f"same id back: {hit['id']}"

    def c6():
        # Gated on check 4. Without that, a client that errors on every create "passes" this.
        if not created:
            return False, "skipped, create did not succeed, so duplicate handling is untested"
        try:
            dup = cms.create_school(test_name, args.city, args.area, email_for(test_name))
        except CMSError as e:
            return True, f"rejected with a clear error, fine: {e}"
        show(dup)
        if str(dup.get("id")) == str(created["id"]):
            return True, "returned the same school instead of a duplicate, fine"
        return False, f"created a second school with the same name and email (id {dup.get('id')}). Needs a unique constraint or a clear error."

    def c7():
        """Every failure has to surface as CMSError. Anything else stops a whole batch of 25 rows."""
        real = os.environ["YS_CMS_BASE_URL"]
        os.environ["YS_CMS_BASE_URL"] = "http://127.0.0.1:9"  # nothing listening
        try:
            dead = ApiCMS()
            dead.search_school(args.known, args.city, args.area)
            return False, "an unreachable CMS raised nothing at all. It must raise CMSError."
        except CMSError as e:
            return True, f"wrapped as CMSError: {str(e)[:120]}"
        except Exception as e:
            return False, (f"an unreachable CMS raised {type(e).__name__}, not CMSError. "
                           "Wrap every failure in CMSError or one bad school kills the batch.")
        finally:
            os.environ["YS_CMS_BASE_URL"] = real

    check("0. the file still matches the contract", c0)
    check("1. known school is found", c1)
    check(f"2. short form {short!r} also finds it", c2)
    check("3. made-up school returns None", c3)
    if args.no_create:
        print("\n--no-create: skipped checks 4-6")
    else:
        check(f"4. create {test_name!r}", c4)
        check("5. the new school is findable by search", c5)
        check("6. creating it twice does not duplicate", c6)
    check("7. failures come back as CMSError", c7)

    failed = [r for r in results if not r[0]]
    print("\n" + "=" * 60)
    for ok, label, note in results:
        print(f"{'PASS' if ok else 'FAIL'}  {label}")
    if created:
        print(f"\nTest school to delete afterwards: id {created['id']}, {test_name!r}")
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
