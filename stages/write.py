"""Stage 4: write one blog with Yellow Slate's own skill, headless."""

import json
import os

import config
from clients import claude_cli
from clients.cms_base import profile_url

TOOLS = ["Skill", "WebSearch", "WebFetch", "Read", "Write", "Edit", "Glob",
         "Bash(curl:*)", "Bash(python:*)", "Bash(mkdir:*)"]


def out_dir(slug):
    return os.path.join("output", slug)


def build_prompt(keyword, city, area, slug, schools):
    """schools: [{"name", "id", "slug"}] in blog order."""
    lines = "\n".join(
        f"     {i}. {s['name']} | CMS ID: {s['id']} | Profile URL: {profile_url(s['slug'])}"
        for i, s in enumerate(schools, 1)
    )
    return config.read_prompt("write_wrapper.md").format(
        keyword=keyword, city=city, area=area, slug=slug, schools=lines, out_dir=out_dir(slug).replace("\\", "/"))


def write_blog(keyword, city, area, slug, schools):
    """Returns path to blog.md. Raises ClaudeError if the run fails or no blog appears."""
    folder = os.path.join(config.ROOT, out_dir(slug))
    os.makedirs(folder, exist_ok=True)
    envelope = claude_cli.run(build_prompt(keyword, city, area, slug, schools),
                              allowed_tools=TOOLS, max_turns=120, timeout=2400)
    with open(os.path.join(folder, "run.json"), "w", encoding="utf-8") as fh:
        json.dump({k: envelope.get(k) for k in ("result", "num_turns", "duration_ms", "total_cost_usd", "session_id")},
                  fh, indent=2)

    blog = os.path.join(folder, "blog.md")
    result = str(envelope.get("result", "")).strip()
    if not os.path.exists(blog):
        raise claude_cli.ClaudeError(f"no blog.md written. Claude said: {result[:300]}")
    if result.upper().startswith("FAILED"):
        raise claude_cli.ClaudeError(result[:300])
    return blog
