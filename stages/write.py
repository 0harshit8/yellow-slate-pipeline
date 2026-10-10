"""Stage 4: write one blog with Yellow Slate's own skill, headless."""

import json
import os
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


def build_prompt(keyword, city, area, slug, schools):
    """schools: [{"name", "id", "slug", "area"}] in blog order.

    Each school carries its OWN locality, which for a city keyword is not the keyword's area.
    The researcher verifies a page against the school's name and locality, so handing it
    "Lucknow" for a school in Gomti Nagar would let the wrong school's fees through.
    """
    lines = "\n".join(
        f"     {i}. {s['name']} | Locality: {s.get('area') or area} | CMS ID: {s['id']}"
        f" | Profile URL: {profile_url(s['slug'])}"
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
    clear_previous(folder)
    os.makedirs(folder, exist_ok=True)
    # WRITE_MODEL is the writer only. The school-researcher subagents keep their own model
    # (opus, set in their definition), which takes precedence over inheriting this one.
    envelope = claude_cli.run(build_prompt(keyword, city, area, slug, schools),
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
