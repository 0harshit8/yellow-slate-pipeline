"""Real Yellow Slate CMS client. Live since their handover on Oct 10, 2026.

Two endpoints:
  GET  /schools/search?name=&city=[&area=]   one match, a candidate list, or nothing
  POST /schools/resolve                      finds or creates, idempotent, returns the school

Their Oct 11, 2026 update changed what a search means, and this client is built on what it
actually does now rather than on the release note. Measured against the live API that day:

  - AREA IS OPTIONAL. name + city returns {"data": {id, name, slug, area, score}} when one
    school fits, and their reply names the area. That is the whole reason stages/area.py is
    now a fallback instead of a gate: for a school already in their CMS we no longer guess
    the locality, we are told it.
  - A SHARED NAME RETURNS CANDIDATES, never a guess: {"data": null, "reason": "ambiguous",
    "candidates": [...]}, each candidate carrying its own area. "Kidzee" in Delhi returns 5.
  - NOTHING FOUND is {"data": null, "reason": "not_found"}, a normal answer and not an error.
    Only an unknown CITY is a 404 now (code UNKNOWN_CITY).
  - AN UNKNOWN AREA NO LONGER FAILS, and this is the trap in the update. A typo'd area comes
    back 200 with "area_matched": false and the search silently widens to the whole city. The
    old client read a 200 as "their CMS knows this area", so after their update that check
    said yes to every typo. So: never trust the area we sent, always take found["area"],
    which is the area their CMS actually has. That alone closes the duplicate-school bug
    stages/area.py was written for.

Two more things their search does NOT do, measured Oct 19, 2026, after their CMS turned
out to hold several schools twice over. Both of these hide a row that is already there, and
a hidden row is created again:

  - AN AREA IS MATCHED ON THE EXACT CHARACTERS, with no prefix or substring work at all.
    Their 15236 sits in "Kalkaji Extension, Block A 10,Govindpuri"; sending "Kalkaji
    Extension" comes back area_matched false. So a search scoped to the locality a page
    gives can never reach a school their CMS filed under a fuller address, and the only
    defence is comparing the two strings here - see stages/area.same_place.
  - A CAMPUS SUFFIX IN THEIR NAME HIDES THE ROW. Their 714 is "Glendale Academy - Sun City
    Campus"; "Glendale Academy" returns not_found even scoped to that row's own area, and
    "Glendale Academy Sun City" returns it at 0.875. So the locality has to go into the
    NAME, not the area, which is what the campus rung below does.

Unchanged, and still the reason the trim ladder exists:
  - A name carrying an extra word misses outright: "Kidzee Preschool" returns not_found in
    the whole of Delhi although "Kidzee" exists five times over. Handing that name straight
    to /resolve would create a sixth. search_school walks a ladder of trimmed names and
    reports which one hit, so a create is never silent about it.
  - Short forms are expanded on their side: "DPS" returns "Delhi Public School" at score 1.
  - Word order and an area inside the name do not matter: "Kalkaji Kidzee" scores 1.
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


# Their candidate list is cut off at five. Measured Oct 19, 2026: "Delhi Public School" in
# Delhi returns exactly 5 (R. K. Puram, Vasant Kunj, Dwarka, Ghaziabad, Mathura Rd) and their
# CMS plainly holds more, "Oakridge International School" in Hyderabad returns 5, "Kendriya
# Vidyalaya" in Delhi 3 and "JSS Public School" in Kolar 2. So a list of five is a truncated
# list and says nothing about a locality missing from it, while a shorter list is the whole
# set. The caller needs that difference before it decides a campus is one they do not have.
CANDIDATE_CAP = 5


class AmbiguousSchool(CMSError):
    """Several schools share this name and nothing in hand picks one of them.

    Raised rather than returned so that "search came back empty" keeps meaning "safe to
    create". An ambiguous name is the opposite of empty: the school is in their CMS several
    times over, and creating would add one more. The caller works out the school's locality
    and searches again with it.
    """

    def __init__(self, message, candidates):
        super().__init__(message)
        self.candidates = candidates
        self.areas = [c.get("area", "") for c in candidates if c.get("area")]
        # a full list is a cut-off list, so "not among these" proves nothing. See CANDIDATE_CAP.
        self.capped = len(candidates) >= CANDIDATE_CAP


def _candidates(name):
    """Short ladder of names to try, most faithful first. Never returns an empty string."""
    name = re.sub(r"\s+", " ", name).strip()
    out = [name]

    # ' - Rajouri Garden, New Delhi' and ', GK-II' style tails that competitors append
    trimmed = re.sub(r"\s*[–—-]\s*.*$", "", name)
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


def names_the_place(school_name, place):
    """True when a school's own name carries this locality, as "... - Sun City Campus" does.

    The whole locality has to appear as consecutive words, so "Sun City" matches "Glendale
    Academy - Sun City Campus" and does not match "Glendale Academy". It is what makes the
    campus rung safe: a hit whose name does NOT carry the locality is not a campus row, and
    appending the locality cannot be what found it.
    """
    words = re.sub(r"[^a-z0-9]+", " ", (place or "").lower()).split()
    if not words:
        return False
    haystack = " " + " ".join(re.sub(r"[^a-z0-9]+", " ", (school_name or "").lower()).split()) + " "
    return f" {' '.join(words)} " in haystack


def _campus_candidates(name, campus):
    """Names to try when their row carries the campus in its own name. Empty when pointless.

    Two rungs at most - the name as the page wrote it and the same with the tail trimmed -
    because this only runs when the plain ladder found nothing and a create is next, and
    four more requests to find that out is not worth it.
    """
    if not (campus or "").strip():
        return []
    ladder, seen = [], set()
    for rung in _candidates(name)[:2]:
        if names_the_place(rung, campus):
            continue                      # the locality is in the name already, so this adds nothing
        candidate = f"{rung} {campus}".strip()
        if candidate.lower() not in seen:
            seen.add(candidate.lower())
            ladder.append(candidate)
    return ladder


def _pick(candidates, area):
    """Choose among same-name schools using the area we were given. None when it cannot.

    With a real area their API scopes the search itself and returns one school, so a
    candidate list arriving alongside a known area means their own CMS holds more than one
    row for that name in that area - ids 7700 and 7712 are both "Kidzee" in Dwarka. Both are
    equally correct, so this takes the lowest id, which is the older row and the one their
    other tables are likeliest to point at, and marks it for review.
    """
    if not area:
        return None
    here = [c for c in candidates if (c.get("area") or "").strip().lower() == area.strip().lower()]
    if not here:
        return None
    return min(here, key=lambda c: int(c["id"]))


class ApiCMS(CMS):
    def __init__(self):
        # Their place list does not change mid-run, so both of these are cached for the run.
        self._areas = {}            # (city.lower(), area.lower()) -> bool
        self._cities = {}           # city.lower() -> bool

    def city_exists(self, city):
        """True if their CMS has this city spelling. One cheap GET per new spelling, cached.

        An unknown city is the one hard 404 left (code UNKNOWN_CITY), so the status tells us
        plainly. A SCHOOL_NOT_FOUND back means the city was fine and the dummy name was not,
        which is the answer we want.
        """
        city = (city or "").strip()
        if not city:
            return False
        if city.lower() not in self._cities:
            try:
                ys_http.call("GET", "schools/search",
                             params={"name": "zzqx no such school", "city": city[:100]})
                self._cities[city.lower()] = True
            except ys_http.NotInCms:
                self._cities[city.lower()] = True       # city fine, name absent
            except ys_http.UnknownPlace:
                self._cities[city.lower()] = False
            except ys_http.YSApiError as exc:
                raise CMSError(str(exc)) from exc
        return self._cities[city.lower()]

    def area_exists(self, city, area):
        """True if their CMS already holds this city + area pair. One cheap GET per new pair.

        Reads "area_matched" off a search for a name that cannot exist, which is the only
        honest signal left: since Oct 11, 2026 an unknown area is answered 200 with
        area_matched false and the search quietly widened to the whole city. Reading the
        status code instead, as this once did, now says yes to every typo.
        """
        city, area = (city or "").strip(), (area or "").strip()
        if not city or not area:
            return False
        key = (city.lower(), area.lower())
        if key not in self._areas:
            try:
                body = ys_http.call("GET", "schools/search",
                                    params={"name": "zzqx no such school", "city": city[:100],
                                            "area": area[:100]})
                self._areas[key] = bool(body.get("area_matched")) if isinstance(body, dict) else False
            except ys_http.NotInCms:
                # no school of that name, which is the point. Their 404 body carries no
                # area_matched, so an area that only this path can see stays unconfirmed.
                self._areas[key] = False
            except ys_http.UnknownPlace:
                self._areas[key] = False
            except ys_http.YSApiError as exc:
                raise CMSError(str(exc)) from exc
        return self._areas[key]

    def search_school(self, name, city, area="", campus=""):
        """Return {"id", "name", "slug", "area", "score", "matched_on", "review", ...} or None.

        "area" is the area THEIR CMS holds for the school, which is the one to file it under,
        not the area passed in - that is only a hint for narrowing a shared name.
        "matched_on" is the name that actually hit, so a match found only after trimming is
        visible downstream. "review" is True when the score is under REVIEW_BELOW, or when
        the pick came out of their own duplicate rows.
        "area_matched" is False when their CMS did not know the area passed in and widened
        the search to the whole city, so the caller can say so rather than file under a typo.

        Walks the whole ladder and keeps the best score rather than taking the first hit,
        because a padded name can match the right school at a poor score while the trimmed
        name matches the same school at 1.0. Measured: "Guru Nanak Public School - Rajouri
        Garden, Delhi" scores 0.889 raw and 1.0 once the tail is dropped. A perfect score
        ends the walk, so the common case is still one request.

        "campus" is the locality the pages put this school in, and it is NEVER sent as the
        area - it is only appended to the name, and only once the plain ladder has come back
        empty and a create is the next thing that would happen. See _by_campus_name.

        Raises AmbiguousSchool when a name matches several schools and the area cannot
        separate them. Returning None there would invite a duplicate.
        """
        best, ambiguous = None, None
        for candidate in _candidates(name):
            params = {"name": candidate[:255], "city": city[:100]}
            if area:
                params["area"] = area[:100]
            try:
                body = ys_http.call("GET", "schools/search", params=params)
            except ys_http.NotInCms:
                continue              # this rung found nothing, try a shorter name
            except ys_http.UnknownPlace as exc:
                # Their CMS does not know this city. Creating would fail the same way, so
                # stop here loudly instead of returning None and failing further on.
                raise CMSError(str(exc)) from exc
            except ys_http.YSApiError as exc:
                raise CMSError(str(exc)) from exc

            found = ys_http.unwrap(body)
            matched = body.get("area_matched") if isinstance(body, dict) else None

            if not found:
                pool = (body.get("candidates") or []) if isinstance(body, dict) else []
                if pool:
                    # an area they did not recognise cannot be used to choose between areas
                    chosen = _pick(pool, area if matched else "")
                    if chosen:
                        found = {**chosen, "review": True}
                    elif ambiguous is None:
                        ambiguous = (candidate, pool)
                if not found:
                    continue

            score = float(found.get("score", 0) or 0)
            if best is None or score > best["score"]:
                best = {
                    "id": int(found["id"]),
                    "name": found.get("name", ""),
                    "slug": found.get("slug", ""),
                    "area": (found.get("area") or "").strip(),
                    "score": score,
                    "matched_on": candidate,
                    "review": score < REVIEW_BELOW or bool(found.get("review")),
                    "area_matched": matched,
                }
            if score >= 1.0:
                break

        if best is None and ambiguous is None:
            best = self._by_campus_name(name, city, campus)

        if best is None and ambiguous:
            rung, pool = ambiguous
            where = ", ".join(f"{c.get('area') or '?'} (id {c.get('id')})" for c in pool[:6])
            raise AmbiguousSchool(
                f"{rung!r} matches {len(pool)} schools in {city}, "
                f"and no area to choose with: {where}",
                pool,
            )
        return best

    def _by_campus_name(self, name, city, campus):
        """One last look before a create: a row whose own NAME carries this locality.

        Their 714 is "Glendale Academy - Sun City Campus" in area "Rajendranagar mandal".
        Measured Oct 19, 2026: "Glendale Academy" returns not_found in Hyderabad even when
        the search is scoped to that row's own area, because the suffix costs it too much
        score. "Glendale Academy Sun City" returns it at 0.875. So the pipeline searched for
        a school their CMS already had live, was told not_found, and created 23236 - a second
        row with Verified = No, which is a dead link in the blog and a hand cleanup for them.

        Never scoped to an area, because the whole point is that their row is filed under an
        area nobody would have guessed. What keeps that safe is names_the_place(): the hit is
        taken only when its own name carries the locality, which is the one thing that makes
        it a campus row rather than a lucky score. Measured on ten schools with no live twin
        (Universal Public School / Laxmi Nagar, Ganga International / Mundka, DAV / Shahdara
        and seven more), this rung returned not_found every time - no false hits.

        The hit comes back flagged for review: its area is one no page mentioned, so a human
        should see which campus the blog ended up pointing at.
        """
        for candidate in _campus_candidates(name, campus):
            try:
                body = ys_http.call("GET", "schools/search",
                                    params={"name": candidate[:255], "city": city[:100]})
            except ys_http.NotInCms:
                continue
            except ys_http.UnknownPlace as exc:
                raise CMSError(str(exc)) from exc
            except ys_http.YSApiError as exc:
                raise CMSError(str(exc)) from exc

            found = ys_http.unwrap(body)
            if not found or not found.get("id"):
                continue
            if not names_the_place(found.get("name", ""), campus):
                # a row of this school the plain ladder could have found, not a campus row.
                # Returning it would claim a campus their name does not actually name.
                continue
            return {
                "id": int(found["id"]),
                "name": found.get("name", ""),
                "slug": found.get("slug", ""),
                "area": (found.get("area") or "").strip(),
                "score": float(found.get("score", 0) or 0),
                "matched_on": candidate,
                "review": True,
                "area_matched": None,
                "campus_in_name": True,
            }
        return None

    def create_school(self, name, city, area, email):
        """Find or create through POST /schools/resolve. Return {"id", "name", "slug", ...}.

        Their endpoint is idempotent: a school that already exists comes back with
        created: false, so a rerun of a failed batch never doubles a row.

        It also reports the area it used, including whether it had to create that area.
        A new area is worth saying out loud: their CMS matches areas on the exact string, so
        "Tilak Nagar" and "Tilaknagar" become two places and split one locality's schools.
        "area_created" carries that up to the caller.
        """
        body = {"name": name[:255], "city": city[:100], "email": email}
        if area:
            body["area"] = area[:100]
        try:
            reply = ys_http.call("POST", "schools/resolve", json_body=body)
        except ys_http.NotInCms as exc:
            # Only reachable without an area: they will not invent a locality for a school
            # they have never seen, so the caller has to supply one.
            raise CMSError(f"{name!r} is not in their CMS and has no area "
                           f"to be created under: {exc}") from exc
        except ys_http.UnknownPlace as exc:
            raise CMSError(str(exc)) from exc
        except ys_http.YSApiError as exc:
            raise CMSError(str(exc)) from exc

        new = ys_http.unwrap(reply) or {}
        if "id" not in new:
            raise CMSError(f"Resolve returned no id for {name!r} in {area}, {city}: {reply}")
        area_info = (reply.get("area") or {}) if isinstance(reply, dict) else {}
        return {
            "id": int(new["id"]),
            "name": new.get("name", name),
            "slug": new.get("slug", ""),
            # their CMS's own area, which is the one to record
            "area": (new.get("area") or area or "").strip(),
            # their flag, not ours: False means the school was already there
            "created": bool(reply.get("created", True)) if isinstance(reply, dict) else True,
            "area_created": bool(area_info.get("created", False)),
        }
