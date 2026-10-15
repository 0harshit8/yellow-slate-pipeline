"""Stage 4: write one blog with Yellow Slate's own skill, headless."""

import json
import os
import re
import shutil
import time

import config
from clients import claude_cli
from clients.cms_base import profile_url
from stages import assets, docx_export, qc

# No shell: images and graphs are done by stages/assets.py after the run.
# Agent spawns the school-researcher subagents (.claude/agents/school-researcher.md), which keep
# each school's search results out of this run's context. The writer keeps WebSearch only for the
# one or two site:yellowslate.com internal-link lookups it still does itself.
TOOLS = ["Skill", "Agent", "WebSearch", "WebFetch", "Read", "Write", "Edit", "Glob", "Grep"]


def out_dir(slug):
    return os.path.join("output", slug)


def _key(name):
    return re.sub(r"[^a-z0-9]+", " ", str(name).lower()).strip()


def pick_ratings(folder):
    """{normalised school name: how many directory ratings the picker counted}.

    stage 1 reads the directory pages and records a rating count per school, then writes it to
    pick.json and nothing ever reads it again. On the Kolar rebuild that threw away a Justdial
    listing with 225 ratings for Sri R.v. School: its researcher went out with no idea the
    listing existed, spent eleven searches, and reported no review signal. Handing the count
    over costs nothing -- the page was already read and paid for in stage 1.

    Returns {} when there is no pick.json, which is every blog picked before this existed.
    """
    path = os.path.join(folder, "pick.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            entries = json.load(fh)
    except (ValueError, OSError):
        return {}  # a pick.json we can't read is not a reason to fail the write
    out = {}
    for s in entries:
        try:
            n = int(s.get("reviews") or 0)
        except (ValueError, TypeError):
            continue
        # max, not last: Kolar's shortlist held Chinmaya Vidyalaya twice, Cottonpet with 210
        # ratings and PC Extn. with none, and the second was overwriting the first. The same
        # name is one school as far as this lookup goes, so keep its best evidence, which is
        # what stages/names.py does when it merges the variants in the first place.
        out[_key(s.get("name"))] = max(out.get(_key(s.get("name")), 0), n)
    return out


def build_prompt(keyword, city, area, slug, schools, ratings=None):
    """schools: [{"name", "id", "slug", "area", "page_name"}] in blog order.

    Each school carries its OWN locality, which for a city keyword is not the keyword's area.
    The researcher verifies a page against the school's name and locality, so handing it
    "Lucknow" for a school in Gomti Nagar would let the wrong school's fees through.

    `ratings` is pick_ratings(). A school the picker saw rated is told so, by the name the
    directory used -- the CMS tab's School column, which is often spelled differently from the
    CMS name. The researcher is then looking for a listing it knows exists rather than guessing
    whether one does.
    """
    ratings = ratings or {}

    def seen(s):
        n = ratings.get(_key(s.get("page_name") or s["name"]), 0)
        return str(n) if n else "NONE"

    lines = "\n".join(
        f"     {i}. {s['name']} | Locality: {s.get('area') or area} | CMS ID: {s['id']}"
        f" | Profile URL: {profile_url(s['slug'])} | Directory ratings: {seen(s)}"
        for i, s in enumerate(schools, 1)
    )
    return config.read_prompt("write_wrapper.md").format(
        keyword=keyword, city=city, area=area, slug=slug, schools=lines,
        budget=f"{qc.word_budget(len(schools)):,}", out_dir=out_dir(slug).replace("\\", "/"))


def clear_previous(folder):
    """Move an earlier run's folder to data/previous_runs/<slug>-<stamp>, so the writer starts
    empty instead of finding the old blog.md and patching it. Returns the new path, or None."""
    if not os.path.isdir(folder) or not os.listdir(folder):
        return None
    dest = os.path.join(os.path.dirname(os.path.dirname(folder)), "data", "previous_runs",
                        f"{os.path.basename(folder)}-{time.strftime('%Y%m%d-%H%M%S')}")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.move(folder, dest)
    return dest


def write_blog(keyword, city, area, slug, schools):
    """Returns path to blog.md. Raises ClaudeError if the run fails or no blog appears."""
    folder = os.path.join(config.ROOT, out_dir(slug))
    # Read before clear_previous moves the folder: pick.json is written there by stage 1.
    ratings = pick_ratings(folder)
    clear_previous(folder)
    os.makedirs(folder, exist_ok=True)
    # WRITE_MODEL is the writer only. The school-researcher subagents keep their own model
    # (opus, set in their definition), which takes precedence over inheriting this one.
    envelope = claude_cli.run(build_prompt(keyword, city, area, slug, schools, ratings),
                              allowed_tools=TOOLS, max_turns=120, timeout=2400,
                              model=config.env("WRITE_MODEL") or None)
    with open(os.path.join(folder, "run.json"), "w", encoding="utf-8") as fh:
        json.dump({k: envelope.get(k) for k in ("result", "num_turns", "duration_ms", "total_cost_usd", "session_id")},
                  fh, indent=2)

    blog = os.path.join(folder, "blog.md")
    result = str(envelope.get("result", "")).strip()
    if not os.path.exists(blog):
        raise claude_cli.ClaudeError(f"no blog.md written. Claude said: {result[:300]}")
    if result.upper().startswith("FAILED"):
        raise claude_cli.ClaudeError(result[:300])
    problems = assets.process(folder)
    try:
        docx_export.export(folder)
    except PermissionError as err:
        problems.append(str(err))
    return blog, problems
