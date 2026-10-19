"""What the pipeline needs from the Yellow Slate CMS. The fake and the real API client both follow this."""

import config


class CMSError(RuntimeError):
    pass


class CMS:
    def search_school(self, name, city, area="", campus=""):
        """Return {"id", "name", "slug", "area"} for an existing school, or None.

        Area is optional and only narrows a name shared by several schools - their API has
        searched by name + city since Oct 11, 2026. The "area" in the answer is the one the
        CMS holds for that school, which is not always the one that was asked for.

        "campus" is the locality the pages put the school in, and it is never sent as an
        area. It is appended to the NAME, and only after a search on the name alone comes
        back empty, because some of their rows carry the campus in their own name and are
        invisible to the plain name: "Glendale Academy" misses "Glendale Academy - Sun City
        Campus" even inside that row's own area. A hit found this way carries
        "campus_in_name": True, and its area is one no page mentioned.

        Raises AmbiguousSchool when the name matches several schools and the area cannot
        separate them, so that None keeps its one meaning: nothing here, safe to create.
        """
        raise NotImplementedError

    def create_school(self, name, city, area, email):
        """Create with verified = No, claimed = No. Return {"id", "name", "slug", "area"}.

        Idempotent: a school that is already there comes back with created = False.
        """
        raise NotImplementedError

    def city_exists(self, city):
        """True if their CMS has this exact city spelling. See stages/city.py for why.

        Their city field is case-insensitive and trims whitespace, but the spelling itself
        must match, and there is no rule for which spelling they use: both "Bengaluru" and
        "Mysore" are theirs, one modern and one not. So this is a question only they answer.
        """
        raise NotImplementedError

    def area_exists(self, city, area):
        """True if the CMS already holds this locality. False means using it creates a place.

        Not a gate on anything - they create missing areas now. It is used to tell a real
        locality their CMS has not seen yet from a typo or a scrap of address, which look
        alike from here and must not be treated alike.
        """
        raise NotImplementedError


def profile_url(slug):
    """Slug is 'city/school-name-area', same shape as Profile URL in their schools.csv."""
    return f"{config.SITE}/{slug.strip('/')}"


def get_cms():
    if config.CMS_MODE == "api":
        from clients.cms_api import ApiCMS
        return ApiCMS()
    from clients.cms_fake import FakeCMS
    return FakeCMS()
