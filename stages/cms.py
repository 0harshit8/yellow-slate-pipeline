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
    """Returns {"id", "name", "slug", "created": bool}."""
    name = cms_name(school, area)
    found = cms.search_school(name, city, area)
    if found:
        return {**found, "created": False}
    new = cms.create_school(name, city, area, school_email(name))
    _log(new, city, area)
    return {**new, "created": True}


def _log(school, city, area):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    line = {"at": datetime.now().isoformat(timespec="seconds"), "city": city, "area": area, **school}
    with open(os.path.join(config.DATA_DIR, "cms_created.log"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(line) + "\n")
