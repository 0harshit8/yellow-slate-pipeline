"""Tavily search + extract. Copied from the AIOS scripts/tavily.py, trimmed to what the pipeline uses."""

import os

import requests

import config

API = "https://api.tavily.com"


class TavilyError(RuntimeError):
    """Raised instead of exiting, so a batch caller can skip one row and continue."""


def _key():
    key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not key:
        raise TavilyError(f"No TAVILY_API_KEY. Set it in {config.ENV_PATH}")
    return key


def _call(path, payload):
    r = requests.post(
        f"{API}/{path}",
        headers={"Authorization": f"Bearer {_key()}", "Content-Type": "application/json"},
        json=payload,
        timeout=90,
    )
    if r.status_code == 401:
        raise TavilyError("Tavily rejected the key (401).")
    if r.status_code == 432:
        raise TavilyError("Tavily is out of credits (432). Check https://app.tavily.com")
    if not r.ok:
        raise TavilyError(f"Tavily error {r.status_code}: {r.text[:400]}")
    return r.json()


def search(query, max_results=10, exclude=None):
    payload = {
        "query": query,
        "max_results": max_results,
        "search_depth": "basic",
        "topic": "general",
        "country": "india",
    }
    if exclude:
        payload["exclude_domains"] = exclude
    return _call("search", payload).get("results", [])


def extract(urls):
    """Returns {url: markdown}. Failed URLs are left out."""
    data = _call("extract", {"urls": urls[:20], "extract_depth": "basic", "format": "markdown"})
    return {r["url"]: r.get("raw_content") or "" for r in data.get("results", [])}
