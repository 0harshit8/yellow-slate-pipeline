"""Paths and settings. Reads .env at the repo root into os.environ (real env vars win)."""

import os

ROOT = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(ROOT, ".env")
OUTPUT_DIR = os.path.join(ROOT, "output")
DATA_DIR = os.path.join(ROOT, "data")
PROMPTS_DIR = os.path.join(ROOT, "prompts")


def load_env():
    """Parsed by hand so there's no python-dotenv dependency."""
    if not os.path.exists(ENV_PATH):
        return
    with open(ENV_PATH, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            os.environ.setdefault(name.strip(), value.strip().strip("'\""))


load_env()


def env(name, default=None):
    return os.environ.get(name, default)


GCP_KEY = env("GCP_KEY", r"C:\Users\Harshit\.aios\gcp-sheets-key.json")
SHEET_ID = env("SHEET_ID", "")
CMS_MODE = env("CMS_MODE", "fake")  # fake | api
SITE = "https://yellowslate.com"


def read_prompt(name):
    with open(os.path.join(PROMPTS_DIR, name), encoding="utf-8") as fh:
        return fh.read()
