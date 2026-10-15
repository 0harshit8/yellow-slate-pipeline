"""Check the Yellow Slate pipeline API end to end. Run before a batch, and after any change on their side.

    py verify_ys_api.py            reads only. Touches nothing in their CMS.
    py verify_ys_api.py --write    also creates one test school, one image and one draft.

The --write run puts real rows in their production CMS. It names everything with a
VERIFY prefix and prints the ids, so the rows are easy to find and delete afterwards.
"""

import argparse
import os
import sys

import config
from clients.cms_base import CMSError
from clients import ys_http

PASS, FAIL, SKIP = "pass", "FAIL", "skip"
results = []


def check(name, fn):
    try:
        detail = fn()
        results.append((PASS, name, detail or ""))
    except Exception as exc:                  # noqa: BLE001 - a failed check must not stop the rest
        results.append((FAIL, name, f"{type(exc).__name__}: {exc}"))


def skip(name, why):
    results.append((SKIP, name, why))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true",
                        help="also run the three create calls against their live CMS")
    args = parser.parse_args()

    if not config.YS_API_KEY:
        print("No YS_API_KEY in .env. Nothing to verify.")
        return 1

    print(f"base: {config.YS_API_BASE}")
    print(f"key:  ...{config.YS_API_KEY[-6:]} ({len(config.YS_API_KEY)} chars)")
    print(f"mode: CMS_MODE={config.CMS_MODE}  BLOG_MODE={config.BLOG_MODE}")
    print()

    # ---- reads -------------------------------------------------------------
    def health():
        body = ys_http.health()
        assert body.get("status") == "ok", body
        return body

    check("health is ok", health)

    from clients.cms_api import ApiCMS, AmbiguousSchool, REVIEW_BELOW
    cms = ApiCMS()

    def doc_example():
        found = cms.search_school("Kidzee Kalkaji", "Delhi", "Kalkaji")
        assert found and found["id"] == 7713, found
        assert found["slug"] == "delhi/kidzee-kalkaji", found
        return f"id {found['id']} score {found['score']}"

    def short_form_expands():
        found = cms.search_school("DPS", "Delhi", "Dwarka")
        assert found and found["name"] == "Delhi Public School", found
        return f"DPS -> {found['name']} (id {found['id']}, score {found['score']})"

    def scoped_to_area():
        here = cms.search_school("Delhi Public School", "Delhi", "Dwarka")
        elsewhere = cms.search_school("Delhi Public School", "Delhi", "Kalkaji")
        assert here and here["slug"].endswith("-dwarka"), here
        assert elsewhere is None, f"Kalkaji should have no DPS, got {elsewhere}"
        return "a school in another area is a different school"

    def nonsense_is_null():
        assert cms.search_school("Zzqx Nonexistent Academy 9981", "Delhi", "Kalkaji") is None
        return "a name that does not exist returns None, not a bad match"

    def trim_ladder_recovers_padded_name():
        """A padded name their search misses outright must still find the existing row.

        "Kidzee Preschool" returns null from their API although "Kidzee" (id 7713) exists,
        so without the ladder this exact case creates a duplicate.
        """
        found = cms.search_school("Kidzee Preschool", "Delhi", "Kalkaji")
        assert found, "Kidzee Preschool found nothing, so it would create a duplicate of 7713"
        assert found["id"] == 7713, found
        assert found["matched_on"] != "Kidzee Preschool", "expected the trimmed name to be the hit"
        return f"id {found['id']} via {found['matched_on']!r} score {found['score']}"

    def ladder_keeps_the_best_score():
        """A tail that scores poorly raw must not be accepted over a clean trimmed match."""
        padded = "Guru Nanak Public School – Rajouri Garden, Delhi"
        found = cms.search_school(padded, "Delhi", "Rajouri Garden")
        assert found and found["id"] == 21704, found
        assert found["score"] >= 1.0, f"took the 0.889 raw match instead of the 1.0 trim: {found}"
        assert found["review"] is False, found
        return f"id {found['id']} score {found['score']} via {found['matched_on']!r}"

    def low_score_is_flagged_for_review():
        """A match under 0.90 must come back with review=True, not be trusted silently."""
        found = cms.search_school("Ganga International School", "Delhi", "Mundka")
        assert found, "expected a match to inspect"
        if found["score"] >= REVIEW_BELOW:
            return f"score {found['score']} is above the {REVIEW_BELOW} floor, nothing to flag"
        assert found["review"] is True, found
        return f"id {found['id']} {found['name']!r} score {found['score']} flagged for review"

    def area_is_optional():
        """Their Oct 11, 2026 change: name + city is enough, and they report the area.

        This is what lets stages/cms.py stop guessing a locality off a competitor page for
        every school. If it ever regresses, that guessing has to come back.
        """
        found = cms.search_school("Sahoday Senior Secondary School", "Delhi")
        assert found, "name + city found nothing, so area is required again"
        assert found["id"] == 15043, found
        assert found["area"] == "Hauz Khas", f"no area in their reply: {found}"
        return f"id {found['id']} placed in {found['area']} with no area sent"

    def a_shared_name_refuses_to_guess():
        """5 Kidzees in Delhi. A guess here is a wrong school in a live blog."""
        try:
            cms.search_school("Kidzee", "Delhi")
        except AmbiguousSchool as exc:
            assert len(exc.candidates) > 1, exc.candidates
            assert exc.areas, "candidates came back with no areas to choose from"
            return f"{len(exc.candidates)} candidates, areas: {', '.join(exc.areas[:4])}"
        raise AssertionError("a name shared by several schools should have raised")

    def an_unknown_area_no_longer_scopes_the_search():
        """The trap in their update, and the reason the old area check had to be rewritten.

        A bad area is answered 200 with area_matched false and the search widens to the whole
        city. Anything reading the status code - as this pipeline did until Oct 11, 2026 -
        now says "yes, their CMS knows that area" about every typo.
        """
        assert cms.area_exists("Delhi", "Kalkaji") is True, "a real area reported as missing"
        assert cms.area_exists("Delhi", "Zzqxville") is False, \
            "a nonsense area reported as real, so a typo would be filed as a new locality"
        return "area_matched separates a real locality from a typo, the status code does not"

    def a_typod_area_does_not_place_a_school_wrongly():
        """With a bad area their search ignores it, so the area in the answer is the truth."""
        found = cms.search_school("Sahoday Senior Secondary School", "Delhi", "Zzqxville")
        assert found and found["id"] == 15043, found
        assert found["area"] == "Hauz Khas", f"filed under the typo instead of their area: {found}"
        assert found["area_matched"] is False, found
        return "their area wins over the one we sent"

    def unknown_city_is_loud():
        try:
            cms.search_school("Kidzee", "Narnia", "Kalkaji")
        except CMSError as exc:
            assert "Narnia" in str(exc), exc
            return "a bad city raises and names the city"
        raise AssertionError("an unknown city should have raised")

    check("search: doc example (Kidzee Kalkaji)", doc_example)
    check("search: short forms expand on their side", short_form_expands)
    check("search: scoped to the area given", scoped_to_area)
    check("search: nonsense returns None", nonsense_is_null)
    check("search: trim ladder recovers a padded name", trim_ladder_recovers_padded_name)
    check("search: ladder keeps the best score", ladder_keeps_the_best_score)
    check("search: a low score is flagged for review", low_score_is_flagged_for_review)
    check("search: area is optional, they report it", area_is_optional)
    check("search: a shared name returns candidates", a_shared_name_refuses_to_guess)
    check("search: an unknown area is detectable", an_unknown_area_no_longer_scopes_the_search)
    check("search: a typo'd area does not misplace", a_typod_area_does_not_place_a_school_wrongly)
    check("search: unknown city raises", unknown_city_is_loud)

    # ---- writes ------------------------------------------------------------
    if not args.write:
        for name in ("create school", "create school is idempotent", "upload image",
                     "create draft", "create draft is idempotent",
                     "draft: empty meta is caught locally"):
            skip(name, "read-only run, pass --write to include it")
        return report()

    stamp = os.environ.get("VERIFY_STAMP", "001")
    school_name = f"VERIFY Delete Me School {stamp}"
    created = {}

    def create_school():
        new = cms.create_school(school_name, "Delhi", "Kalkaji",
                                f"verify-delete-me-{stamp}@schools.yellowslate.com")
        created.update(new)
        assert new["id"], new
        return f"id {new['id']}  slug {new['slug']}  created={new['created']}"

    def create_is_idempotent():
        again = cms.create_school(school_name, "Delhi", "Kalkaji",
                                  f"verify-delete-me-{stamp}@schools.yellowslate.com")
        assert again["id"] == created["id"], f"second create made a new row: {again}"
        assert again["created"] is False, f"expected created=false on the second call, got {again}"
        return f"same id {again['id']}, created=False"

    check("create school", create_school)
    check("create school is idempotent", create_is_idempotent)

    from clients.blog_api import ApiBlog
    blog = ApiBlog()
    image_url = {}

    def upload_image():
        path = os.path.join(config.OUTPUT_DIR, f"verify-{stamp}.png")
        os.makedirs(config.OUTPUT_DIR, exist_ok=True)
        if not os.path.exists(path):
            # smallest valid 1x1 png, so the check does not depend on a file in the repo
            import base64
            png = base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/"
                "q842iQAAAABJRU5ErkJggg=="
            )
            with open(path, "wb") as fh:
                fh.write(png)
        out = blog.upload_image(path, alt="Verify run, safe to delete")
        image_url.update(out)
        assert out["url"].startswith("http"), out
        return out["url"]

    slug = f"verify-delete-me-{stamp}"
    draft = {}

    def create_draft():
        school_id = created.get("id", 7713)
        body = f'<h2>1. {school_name}</h2><p>[btn_admissions id="{school_id}"]</p>'
        if image_url:
            body += f'<p><img src="{image_url["url"]}" alt="verify"></p>'
        out = blog.create_draft({
            "title": f"VERIFY Delete Me {stamp}",
            "meta_title": f"VERIFY Delete Me {stamp}",
            "meta_description": "Verification run from the OtivaxAI pipeline. Safe to delete.",
            "slug": slug,
            "city": "Delhi",
            "area": "Kalkaji",
            "content": body,
        })
        draft.update(out)
        assert out["status"] == "draft", out
        return (f"id {out['id']}  status {out['status']}  linked_schools {out['linked_schools']}\n"
                f"       edit: {out['edit_url']}")

    def draft_is_idempotent():
        """Same slug twice must return the same draft. Batches get retried, so this will happen.

        meta_title and meta_description are sent in full: their API rejects either one empty
        with a 400 that names neither field, which is not in their docs.
        """
        again = blog.create_draft({
            "title": f"VERIFY Delete Me {stamp}",
            "meta_title": f"VERIFY Delete Me {stamp}",
            "meta_description": "Second call, checking the slug is idempotent. Safe to delete.",
            "slug": slug, "city": "Delhi", "area": "Kalkaji",
            "content": "<p>second call</p>",
        })
        assert again["id"] == draft["id"], f"second create made a new draft: {again}"
        assert again["created"] is False, f"expected created=false, got {again}"
        return f"same id {again['id']}, created=False"

    def empty_meta_is_caught_before_the_api():
        """The guard must fire locally, so a 600-blog batch names the row and the field."""
        try:
            blog.create_draft({
                "title": "x", "meta_title": "", "meta_description": "d",
                "slug": "verify-should-never-be-created", "city": "Delhi", "area": "Kalkaji",
                "content": "<p>x</p>",
            })
        except Exception as exc:
            assert "meta_title" in str(exc), exc
            return "empty meta_title refused locally, no request sent"
        raise AssertionError("an empty meta_title should have been refused before the request")

    check("upload image", upload_image)
    check("create draft", create_draft)
    check("create draft is idempotent", draft_is_idempotent)
    check("draft: empty meta is caught locally", empty_meta_is_caught_before_the_api)

    return report(cleanup=(created, draft))


def report(cleanup=None):
    print(f"{'':2} {'check':<46} detail")
    print("-" * 100)
    for status, name, detail in results:
        mark = {PASS: "ok", FAIL: "XX", SKIP: "--"}[status]
        print(f"{mark:2} {name:<46} {detail}")
    print("-" * 100)
    failed = sum(1 for s, _, _ in results if s == FAIL)
    passed = sum(1 for s, _, _ in results if s == PASS)
    skipped = sum(1 for s, _, _ in results if s == SKIP)
    print(f"{passed} passed, {failed} failed, {skipped} skipped")

    if cleanup:
        school, draft = cleanup
        print()
        print("DELETE THESE BY HAND in their dashboard, they are real rows:")
        if school.get("id"):
            print(f"  school {school['id']}  {school.get('slug', '')}")
        if draft.get("id"):
            print(f"  draft  {draft['id']}  {draft.get('edit_url', '')}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
