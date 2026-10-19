"""Stand-in for the Yellow Slate CMS until their API exists. Stores schools in a JSON file.

Mirrors the live API as measured on Oct 11, 2026, so a fake run and a real run fail in the
same places: area is optional on search, a name shared by several schools raises
AmbiguousSchool instead of guessing, and the answer carries the area the CMS holds.
Slug pattern copied from their admin: city/school-name-area (school names already end with
the area, so it appears twice).
"""

import json
import os

import config
from clients.cms_base import CMS, CMSError
from stages.names import MERGE_THRESHOLD, similar, slugify

FIRST_ID = 900001  # far above their real IDs (~23,000) so fake data is obvious


class FakeCMS(CMS):
    def __init__(self, path=None, areas=(), cities=()):
        self.path = path or os.path.join(config.DATA_DIR, "fake_cms.json")
        self.schools = []
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as fh:
                self.schools = json.load(fh)
        # Localities their CMS holds that have no school in them yet. The real CMS has
        # thousands; without any, this fake cannot tell a genuine new campus in a real
        # locality from a typo, which is the distinction stages/cms.py turns on.
        self.known_areas = {(a or "").strip().lower() for a in areas if (a or "").strip()}
        # Cities their CMS has, with or without a school stored here yet. Their spellings are
        # not derivable (see stages/city.py), so a test says which ones exist.
        self.known_cities = {(c or "").strip().lower() for c in cities if (c or "").strip()}

    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(self.schools, fh, indent=2)

    def city_exists(self, city):
        """True for a seeded city, or one a stored school sits in. See CMS.city_exists."""
        city = (city or "").strip()
        if not city:
            return False
        if city.lower() in self.known_cities:
            return True
        return any(s["city"].lower() == city.lower() for s in self.schools)

    def area_exists(self, city, area):
        """True for a seeded locality, or one a stored school sits in. See CMS.area_exists."""
        area = (area or "").strip()
        if not (city or "").strip() or not area:
            return False
        if area.lower() in self.known_areas:
            return True
        return any(s["city"].lower() == city.strip().lower()
                   and s["area"].lower() == area.lower() for s in self.schools)

    def search_school(self, name, city, area="", campus=""):
        """Name + city, narrowed by area only when one is given. See CMS.search_school.

        An area the store does not have is IGNORED rather than applied, and reported with
        "area_matched": false, because that is what their live API does since Oct 11, 2026.
        Filtering on it instead would make a typo look like "no school there" in fake mode
        and like "here is a school across the city" in real mode, and the code that tells
        those apart would only ever be exercised against production.

        The campus rung is mirrored for the same reason: a row whose own name carries the
        locality is invisible to a search on the plain name both here and there, and the
        measurement that proved it is in ApiCMS._by_campus_name.
        """
        from clients.cms_api import AmbiguousSchool, CANDIDATE_CAP

        scoped = bool(area) and self.area_exists(city, area)
        hits = []
        for s in self.schools:
            if s["city"].lower() != city.lower():
                continue
            if scoped and s["area"].lower() != area.strip().lower():
                continue
            score = similar(name, s["name"], places=(city, s["area"]))
            if score >= MERGE_THRESHOLD:
                hits.append((score, s))
        if not hits:
            return self._by_campus_name(name, city, campus)

        top = max(score for score, _ in hits)
        joint = [s for score, s in hits if score == top]
        if len(joint) > 1 and len({s["area"].lower() for s in joint}) > 1:
            pool = [{"id": s["id"], "name": s["name"], "slug": s["slug"], "area": s["area"],
                     "score": top} for s in joint][:CANDIDATE_CAP]
            raise AmbiguousSchool(
                f"{name!r} matches {len(pool)} schools in {city}, and no area to choose with: "
                + ", ".join(f"{s['area']} (id {s['id']})" for s in pool[:6]), pool)

        best = min(joint, key=lambda s: s["id"])
        return {"id": best["id"], "name": best["name"], "slug": best["slug"],
                "area": best["area"], "score": top, "matched_on": name,
                "review": top < 1.0,
                "area_matched": scoped if area else None}

    def _by_campus_name(self, name, city, campus):
        """The plain name found nothing, so try it with the locality appended, city-wide.

        Mirrors ApiCMS._by_campus_name, flags included: never scoped to an area, and the hit
        is taken only when the row's own name carries the locality.
        """
        from clients.cms_api import _campus_candidates, names_the_place

        for candidate in _campus_candidates(name, campus):
            hits = [(similar(candidate, s["name"], places=(city, s["area"])), s)
                    for s in self.schools if s["city"].lower() == city.lower()
                    and names_the_place(s["name"], campus)]
            hits = [(score, s) for score, s in hits if score >= MERGE_THRESHOLD]
            if not hits:
                continue
            top = max(score for score, _ in hits)
            best = min((s for score, s in hits if score == top), key=lambda s: s["id"])
            return {"id": best["id"], "name": best["name"], "slug": best["slug"],
                    "area": best["area"], "score": top, "matched_on": candidate,
                    "review": True, "area_matched": None, "campus_in_name": True}
        return None

    def create_school(self, name, city, area, email):
        if any(s["email"] == email for s in self.schools):
            raise CMSError(f"email already used: {email}")
        new = {
            "id": max([s["id"] for s in self.schools], default=FIRST_ID - 1) + 1,
            "name": name,
            "slug": f"{slugify(city)}/{slugify(name)}-{slugify(area)}",
            "city": city,
            "area": area,
            "email": email,
            "verified": False,
            "claimed": False,
        }
        made_area = not any(s["city"].lower() == city.lower()
                            and s["area"].lower() == area.lower() for s in self.schools)
        self.schools.append(new)
        self._save()
        return {"id": new["id"], "name": new["name"], "slug": new["slug"],
                "area": new["area"], "created": True, "area_created": made_area}
