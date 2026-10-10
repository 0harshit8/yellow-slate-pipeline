"""Real Yellow Slate CMS client. Fill in the two TODOs, then run verify_cms_api.py.

Drops back into the pipeline as clients/cms_api.py. Only this file changes.

Contract, in full:

    search_school(name, city, area)
        -> {"id": int, "name": str, "slug": str}   an existing school in this city + area
        -> None                                     no match
        name is a full name including the area ("Delhi Public School Kalkaji").
        Loose on the name, exact on city + area.

    create_school(name, city, area, email)
        -> {"id": int, "name": str, "slug": str}
        verified = No, claimed = No. Cities and areas already exist, never created here.
        Raises CMSError on any failure, with the API's message in it.

    id   = slate ID, the one used in [btn_admissions id="XXX"]
    slug = profile URL path, same value as Profile URL in the schools CSV ("city/school-name-area")
"""

import os

import requests

from clients.cms_base import CMS, CMSError

TIMEOUT = 30


def _base_url():
    url = os.environ.get("YS_CMS_BASE_URL", "").strip().rstrip("/")
    if not url:
        raise CMSError("No YS_CMS_BASE_URL set.")
    return url


def _key():
    key = os.environ.get("YS_CMS_API_KEY", "").strip()
    if not key:
        raise CMSError("No YS_CMS_API_KEY set.")
    return key


def _headers():
    # TODO: confirm the auth header the CMS expects.
    return {"Authorization": f"Bearer {_key()}", "Content-Type": "application/json"}


def _call(method, path, **kwargs):
    """One place for every request, so errors and timeouts behave the same everywhere."""
    r = requests.request(method, f"{_base_url()}/{path.lstrip('/')}",
                         headers=_headers(), timeout=TIMEOUT, **kwargs)
    if r.status_code in (401, 403):
        raise CMSError(f"CMS rejected the key ({r.status_code}).")
    if not r.ok:
        raise CMSError(f"CMS error {r.status_code} on {method} {path}: {r.text[:400]}")
    try:
        return r.json()
    except ValueError:
        raise CMSError(f"CMS returned non-JSON on {method} {path}: {r.text[:200]}")


class ApiCMS(CMS):
    def search_school(self, name, city, area):
        # TODO: call the search endpoint and map its response to {"id", "name", "slug"} or None.
        #
        # Example of the shape expected back, nothing more:
        #   data = _call("GET", "schools/search", params={"q": name, "city": city, "area": area})
        #   hits = data.get("data") or []
        #   if not hits:
        #       return None
        #   top = hits[0]
        #   return {"id": int(top["id"]), "name": top["name"], "slug": top["slug"]}
        #
        # Must return None (not {}, not an exception) when the school does not exist.
        raise CMSError("search_school not implemented yet")

    def create_school(self, name, city, area, email):
        # TODO: call the create endpoint with verified = No and claimed = No,
        # and map its response to {"id", "name", "slug"}.
        #
        #   data = _call("POST", "schools", json={
        #       "name": name, "city": city, "area": area, "email": email,
        #       "verified": False, "claimed": False,
        #   })
        #   new = data.get("data") or data
        #   return {"id": int(new["id"]), "name": new["name"], "slug": new["slug"]}
        #
        # Raise CMSError on failure. The caller retries failed rows later.
        raise CMSError("create_school not implemented yet")
