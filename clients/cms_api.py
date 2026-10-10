"""Real Yellow Slate CMS client. Live since their handover on Oct 10, 2026.

Two endpoints:
  GET  /schools/search?name=&city=&area=   one best match, or data: null
  POST /schools                            201 when new, 200 when it already existed

Three things about their search that this client relies on, measured against the live API
on Oct 10, 2026 rather than taken from the docs:

  - Matching is scoped to the city + area given. "Delhi Public School" in Dwarka returns the
    Dwarka campus; the same name in Kalkaji returns null. So a school in another area is
    correctly a different school, and a null means "not in this area", not "not in the CMS".
  - Short forms are expanded on their side: "DPS" returns "Delhi Public School" at score 1.
    So the pipeline does not need to expand names before searching.
  - The area inside the name is ignored, and word order does not matter: "Kidzee Kalkaji" and
    "Kalkaji Kidzee" both return "Kidzee" at score 1.

What their search will NOT match, and why create_school is still risky:
  - A name carrying an extra word: "Kidzee Preschool" returns null although "Kidzee" exists.
  - A prefix: "Kidz" returns null.
  So a competitor page that pads a name produces a null and would create a duplicate of a
  school already in their 15,878. search_school walks a short ladder of trimmed names before
  it gives up, and reports which one hit so a create is never silent about it.
"""

import re

from clients.cms_base import CMS, CMSError
from clients import ys_http

# Below this, their match is reported but flagged for review rather than trusted outright.
# Measured: a clean hit scores 1.0, a one-letter typo 0.909, and "Ganga International School"
# matched a different Mundka school at 0.852. Anything under 0.90 gets human eyes.
REVIEW_BELOW = 0.90

# Words that pad a school name on a competitor page but are usually absent from the CMS row.
# Order matters: the ladder drops tails first, then these, never the distinctive part.
_PADDING = re.compile(
    r"\b(pre[- ]?school|play\s*school|nursery|senior\s+secondary|sr\.?\s*sec\.?|"
    r"higher\s+secondary|co[- ]?ed(ucational)?|convent|public|international|global|world|model)\b",
    re.I,
)


def _candidates(name):
    """Short ladder of names to try, most faithful first. Never returns an empty string."""
    name = re.sub(r"\s+", " ", name).strip()
    out = [name]

    # ' – Rajouri Garden, New Delhi' and ', GK-II' style tails that competitors append
    trimmed = re.sub(r"\s*[\u2013\u2014-]\s*.*$", "", name)
    trimmed = re.sub(r",.*$", "", trimmed)
    trimmed = re.sub(r"\((?!.*\b(?:DPSR|KV)\b).*?\)", "", trimmed).strip(" .,-")
    out.append(trimmed)

    # same, minus the padding words, keeping 'School' on the end so it still reads as a school
    bare = _PADDING.sub(" ", trimmed)
    bare = re.sub(r"\s+", " ", bare).strip(" .,-")
    if bare and not re.search(r"\bschool\b", bare, re.I):
        out.append(f"{bare} School")
    out.append(bare)

    seen, ladder = set(), []
    for candidate in out:
        key = candidate.lower()
        if candidate and key not in seen and len(candidate) > 2:
            seen.add(key)
            ladder.append(candidate)
    return ladder or [name]


class ApiCMS(CMS):
    def search_school(self, name, city, area):
        """Return {"id", "name", "slug", "score", "matched_on", "review"} or None.

        "matched_on" is the name that actually hit, so a match found only after trimming is
        visible downstream. "review" is True when the score is under REVIEW_BELOW.

        Walks the whole ladder and keeps the best score rather than taking the first hit,
        because a padded name can match the right school at a poor score while the trimmed
        name matches the same school at 1.0. Measured: "Guru Nanak Public School - Rajouri
        Garden, Delhi" scores 0.889 raw and 1.0 once the tail is dropped. A perfect score
        ends the walk, so the common case is still one request.
        """
        best = None
        for candidate in _candidates(name):
            try:
                body = ys_http.call("GET", "schools/search",
                                    params={"name": candidate[:255], "city": city[:100], "area": area[:100]})
            except ys_http.UnknownPlace as exc:
                # Their CMS does not know this city or area. Creating would 404 too, so stop here
                # loudly instead of returning None and letting create_school fail further on.
                raise CMSError(str(exc)) from exc
            except ys_http.YSApiError as exc:
                raise CMSError(str(exc)) from exc

            found = ys_http.unwrap(body)
            if not found:
                continue

            score = float(found.get("score", 0) or 0)
            if best is None or score > best["score"]:
                best = {
                    "id": int(found["id"]),
                    "name": found.get("name", ""),
                    "slug": found.get("slug", ""),
                    "score": score,
                    "matched_on": candidate,
                    "review": score < REVIEW_BELOW,
                }
            if score >= 1.0:
                break
        return best

    def create_school(self, name, city, area, email):
        """Create with verified = 0 and claimed = 0. Return {"id", "name", "slug", "created"}.

        Their endpoint is idempotent: a school that already exists comes back as 200 with
        created: false, so a rerun of a failed batch never doubles a row.
        """
        try:
            body = ys_http.call("POST", "schools", json_body={
                "name": name[:255],
                "city": city[:100],
                "area": area[:100],
                "email": email,
            })
        except ys_http.UnknownPlace as exc:
            raise CMSError(str(exc)) from exc
        except ys_http.YSApiError as exc:
            raise CMSError(str(exc)) from exc

        new = ys_http.unwrap(body) or {}
        if "id" not in new:
            raise CMSError(f"Create returned no id for {name!r} in {area}, {city}: {body}")
        return {
            "id": int(new["id"]),
            "name": new.get("name", name),
            "slug": new.get("slug", ""),
            # their flag, not ours: False means the school was already there
            "created": bool(body.get("created", True)) if isinstance(body, dict) else True,
        }
