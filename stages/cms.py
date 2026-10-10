"""Stage 3: make sure every approved school exists in the CMS and get its ID + slug.

Always searches before creating, so a rerun never makes duplicates.
Every school we create is appended to data/cms_created.log.
"""

import json
import os
from datetime import datetime

import config
from stages.names import cms_name, school_email


def ensure_school(cms, school, city, area):
    """Returns {"id", "name", "slug", "created": bool}, plus "score" and "review" on a match.

    Searches on the name as the competitor page wrote it, not the trimmed one. Their matching
    ignores an area inside the name, and clients/cms_api.py walks its own ladder of shorter
    names, so the fuller string gives the search more to work with and never matches less.
    Creates under cms_name(), which is the plain name their CMS expects.
    """
    found = cms.search_school(school, city, area)
    if found:
        return {**found, "created": False}
    name = cms_name(school, area)
    new = cms.create_school(name, city, area, school_email(name, city, area))
    _log(new, city, area)
    return {**new, "created": True}


def _log(school, city, area):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    line = {"at": datetime.now().isoformat(timespec="seconds"), "city": city, "area": area, **school}
    with open(os.path.join(config.DATA_DIR, "cms_created.log"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(line) + "\n")
