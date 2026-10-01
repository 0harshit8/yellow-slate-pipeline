"""DataForSEO Google Ads search volume, India.

Billed per task, not per keyword (live: $0.09 a task, up to 1,000 keywords),
so always send names in one batch. One task per blog would cost ~$54 for 600 blogs;
batched it's under $1.
"""

import os
import re

import requests

import config  # noqa: F401  loads .env

URL = "https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/live"
INDIA = 2356
BATCH = 1000


class DataForSEOError(RuntimeError):
    pass


def clean(keyword):
    """Google Ads rejects punctuation-heavy keywords and anything over 80 chars / 10 words."""
    k = re.sub(r"[^a-z0-9 ]", " ", keyword.lower())
    words = k.split()[:10]
    return " ".join(words)[:80].strip()


def search_volume(keywords):
    """Returns {cleaned keyword: monthly volume or 0}. One task per 1,000 keywords."""
    login, password = os.environ.get("DATAFORSEO_LOGIN"), os.environ.get("DATAFORSEO_PASSWORD")
    if not login or not password:
        raise DataForSEOError("DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD missing in .env")
    unique = sorted({clean(k) for k in keywords if clean(k)})
    out = {}
    for i in range(0, len(unique), BATCH):
        chunk = unique[i:i + BATCH]
        r = requests.post(URL, auth=(login, password), timeout=120,
                          json=[{"keywords": chunk, "location_code": INDIA, "language_code": "en"}])
        if not r.ok:
            raise DataForSEOError(f"DataForSEO HTTP {r.status_code}: {r.text[:300]}")
        task = (r.json().get("tasks") or [{}])[0]
        if task.get("status_code") != 20000:
            raise DataForSEOError(f"DataForSEO: {task.get('status_code')} {task.get('status_message')}")
        for item in task.get("result") or []:
            out[item["keyword"]] = item.get("search_volume") or 0
        for k in chunk:
            out.setdefault(k, 0)
    return out
