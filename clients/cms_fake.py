"""Stand-in for the Yellow Slate CMS until their API exists. Stores schools in a JSON file.

Mirrors what we asked their tech team for: search by name + city + area with loose
name matching, create returns id + slug. Slug pattern copied from their admin:
city/school-name-area (school names already end with the area, so it appears twice).
"""

import json
import os

import config
from clients.cms_base import CMS, CMSError
from stages.names import MERGE_THRESHOLD, similar, slugify

FIRST_ID = 900001  # far above their real IDs (~23,000) so fake data is obvious


class FakeCMS(CMS):
    def __init__(self, path=None):
        self.path = path or os.path.join(config.DATA_DIR, "fake_cms.json")
        self.schools = []
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as fh:
                self.schools = json.load(fh)

    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(self.schools, fh, indent=2)

    def search_school(self, name, city, area):
        best, best_score = None, 0.0
        for s in self.schools:
            if s["city"].lower() != city.lower() or s["area"].lower() != area.lower():
                continue
            score = similar(name, s["name"], places=(city, area))
            if score > best_score:
                best, best_score = s, score
        if best and best_score >= MERGE_THRESHOLD:
            return {"id": best["id"], "name": best["name"], "slug": best["slug"]}
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
        self.schools.append(new)
        self._save()
        return {"id": new["id"], "name": new["name"], "slug": new["slug"]}
