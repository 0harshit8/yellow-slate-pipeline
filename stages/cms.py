"""Stage 3: make sure every approved school exists in the CMS and get its ID + slug.

Always searches before creating, so a rerun never makes duplicates.
Every school we create is appended to data/cms_created.log.

The order of business changed with their Oct 11, 2026 API update. It used to be: work out the
school's locality, then search that one locality, then create there. Now it is:

    search the whole city by name  ->  their reply names the area
    only if that cannot settle it  ->  work out a locality and try again

Which matters because the locality we worked out was a guess off a competitor page, and the
area their CMS holds is a fact. Guessing is now the exception, not the rule, and the two
cases that still need it are a name shared by several schools and a school they do not have.
"""

import json
import os
from datetime import datetime

import config
from clients.cms_base import CMSError
from clients.cms_api import AmbiguousSchool
from stages import area as area_stage
from stages.names import cms_name, school_email


class UnplaceableSchool(CMSError):
    """No locality could be found for this school, so it is dropped from the blog.

    Separate from CMSError because it is not a batch-stopping fault: one school out of ten
    could not be placed, the other nine are fine, and the blog carries on without it.
    """


def ensure_school(cms, school, city, page_area="", blog_area=""):
    """Returns {"id", "name", "slug", "area", "created", "note"}, plus "score"/"review" on a match.

    Searches on the name as the competitor page wrote it, not the trimmed one. Their matching
    ignores an area inside the name, and clients/cms_api.py walks its own ladder of shorter
    names, so the fuller string gives the search more to work with and never matches less.

    "area" in the answer is always the area their CMS holds, never the one guessed here, so a
    school found in Hauz Khas is recorded in Hauz Khas even when the page said otherwise.

    Raises UnplaceableSchool when the school is neither findable nor placeable.
    """
    try:
        found = cms.search_school(school, city)
        note = "found by name and city"
    except AmbiguousSchool as exc:
        # Their CMS has this name in several places and will not guess between them, so a
        # locality has to come from somewhere else. Prefer one of the areas they offered,
        # because matching one of those rows is always better than making a new one.
        #
        # Their candidate list is capped at 5 though (measured Oct 11, 2026: "Delhi Public
        # School", "Kidzee" and "DAV Public School" all return exactly 5 in Delhi, and DPS
        # alone has more). So "not among the candidates" does not mean "does not exist", and
        # treating it that way would drop a school whose locality is real but sixth in line.
        # When that happens, resolve freely and let a scoped search decide: their API scopes
        # properly when the area is real, so a hit is the row and a miss is a new campus.
        area, why = area_stage.resolve(school, city, page_area, blog_area=blog_area,
                                       among=exc.areas)
        if not area:
            area, why = area_stage.resolve(school, city, page_area, blog_area=blog_area)
            if not area:
                raise UnplaceableSchool(f"{school}: {why}") from exc
        try:
            found = cms.search_school(school, city, area)
        except AmbiguousSchool as again:
            # The locality got past resolve() and still did not scope their search, so it is
            # not one they hold: they ignored it and handed back the whole city, ambiguous
            # exactly as before. Nothing else here can choose between those rows, so this is
            # one school that cannot be placed - which is a skip, not a dead batch. Letting
            # the raw AmbiguousSchool through lost ten good schools over one spelling.
            raise UnplaceableSchool(
                f"{school}: {area!r} ({why}) is not a locality their CMS holds, so the "
                f"search widened back to the city: {again}") from again
        note = f"shared name, placed in {area} {why}"
        if found and found.get("area_matched") is False:
            # the locality is not one of theirs, so that hit is just the city-wide match
            found = None
        if not found:
            if not cms.area_exists(city, area):
                raise UnplaceableSchool(
                    f"{school}: their CMS has this name in {', '.join(exc.areas) or 'no areas'}, "
                    f"and {area!r} is not a locality they have") from exc
            found = None            # a real locality with no such school: a new campus
            note = f"shared name, {area} is a campus they do not have"

    if found:
        settled, why = _same_campus(cms, school, city, page_area, found)
        if settled:
            _check_row(school, settled)
            return {**settled, "created": False,
                    "note": f"{note}, {why}".rstrip(", ") if why else note}
        # The pages put this school in a locality their CMS knows, and the school their CMS
        # returned is in a different one, so these are two campuses of one chain and the one
        # we want is not in their CMS. Fall through and create it.
        note = "other campuses exist, this one is new"

    # Not in their CMS at all, so it has to be created, and creating needs a locality.
    area, why = area_stage.resolve(school, city, page_area, blog_area=blog_area)
    if not area:
        raise UnplaceableSchool(f"{school}: {why}")

    name = cms_name(school, area)
    new = cms.create_school(name, city, area, school_email(name, city, area))
    _log(new, city, new.get("area", area))
    made = "new locality " if new.get("area_created") else ""
    return {**new, "created": True,
            "note": f"{note}, created in {made}{new.get('area', area)} {why}".lstrip(", ")}


def _check_row(school, found):
    """Refuse a CMS row that cannot be linked to. Raises UnplaceableSchool, naming the id.

    Not every row in their 15,878 is complete. Measured Oct 11, 2026, school 8010 is
    "DAV Public School" with area null and slug "/dav-public-school-" - no city, no locality.
    Its profile URL comes out as a dead link, and a listicle that publishes one is worse than
    a listicle with nine schools in it. So this drops the school and names the row, which is
    something Yellow Slate can fix at their end.
    """
    slug = (found.get("slug") or "").strip().strip("/")
    if not found.get("area") or not slug or "/" not in slug:
        raise UnplaceableSchool(
            f"{school}: their row {found.get('id')} is incomplete "
            f"(area {found.get('area') or 'missing'!r}, slug {found.get('slug') or 'missing'!r}), "
            f"so it has no working profile URL. Ask Yellow Slate to fix that row.")


def _same_campus(cms, school, city, page_area, found):
    """Guard against merging two campuses of one chain. Returns (school to use, why).

    A city-wide search is what makes the rest of this simple, and this is the one place it
    can be too generous. "Delhi Public School" in Delhi with only the Kalkaji campus in their
    CMS returns Kalkaji at score 1.0 even when the blog is about the Saket campus, and taking
    it would hang a Saket listicle off a Kalkaji row.

    So when the pages named a locality and their CMS placed the school somewhere else:
      - search again inside the locality the pages gave. A hit genuinely scoped to it is the
        right campus.
      - no hit, and their CMS knows that locality: a real place with no school of this name
        in it, so this campus is genuinely missing. Return None, and the caller creates it.
      - no hit, and their CMS does not know the locality: far more likely a typo or a scrap
        of address than a new campus, so keep their match and flag it for a human.

    The re-search needs the same care as everything else since their Oct 11, 2026 update: an
    area they do not know is ignored rather than refused, so a search "inside Haus Khaas"
    quietly becomes a search across Delhi and hands back the very school it was meant to
    test. "area_matched": false is what separates a real hit in that locality from that, and
    reading the hit alone makes a typo look like confirmation.
    """
    wanted = area_stage.clean(page_area, city)
    theirs = (found.get("area") or "").strip()
    # Two spellings of one locality are one place, not two campuses. Their CMS splits a
    # locality whenever the characters differ, so raw text here turns the empty half of a
    # split into "a real place with no school in it" and creates a duplicate under it.
    if not wanted or not theirs or area_stage.same_place(wanted, theirs, city):
        return found, ""
    if not area_stage.usable(city, wanted):
        return found, ""

    try:
        here = cms.search_school(school, city, wanted)
    except AmbiguousSchool:
        here = None                      # their own duplicate rows in that one locality
    if here and here.get("area_matched") is not False:
        return here, f"the pages put it in {wanted}, and their CMS has it there"
    if cms.area_exists(city, wanted):
        return None, ""
    return ({**found, "review": True},
            f"the pages said {wanted!r}, which their CMS does not have, so their "
            f"{theirs} match is kept for review")


def _log(school, city, area):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    line = {"at": datetime.now().isoformat(timespec="seconds"), "city": city, "area": area, **school}
    with open(os.path.join(config.DATA_DIR, "cms_created.log"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(line) + "\n")
