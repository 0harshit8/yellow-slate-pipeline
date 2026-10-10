"""Headless Claude Code. Runs `claude -p` in the repo so the project skill is found."""

import json
import re
import subprocess

import config


class ClaudeError(RuntimeError):
    pass


def run(prompt, allowed_tools=None, max_turns=40, timeout=1800, model=None):
    """Run one headless session. Returns the parsed --output-format json envelope.

    Both tool flags are needed, because they do different jobs: --tools decides
    which definitions are sent at all (an unlisted tool costs no context), while
    --allowedTools pre-approves them (an unapproved tool is offered, then denied,
    which is how a headless run silently loses WebFetch). Sending only the tools
    the stage uses cuts the preamble the write stage repeats on each of its ~36
    calls from about 44k tokens to 14k. --strict-mcp-config skips the MCP servers
    (none are used here) and --setting-sources project skips user-level settings
    and hooks; the project's own .claude/skills is still read, so the skill loads.
    An empty --tools means no tools at all, which is what the pick prompt asks for.

    Subagents: the write stage spawns school-researcher, defined in the project's
    .claude/agents/. That should be covered by --setting-sources project, the same way
    .claude/skills is, but it is not spelled out in `claude --help`. If a run ever fails with
    "school-researcher agent not found", pass the definition explicitly instead:
    --agents '{"school-researcher": {"description": ..., "prompt": ...}}' built from that file.
    The write prompt is told to fail loudly rather than research the schools itself, so this
    shows up as a FAILED row and never as a quietly worse blog.
    """
    cmd = ["claude", "-p", "--output-format", "json", "--max-turns", str(max_turns),
           "--strict-mcp-config", "--setting-sources", "project",
           "--tools", ",".join(allowed_tools) if allowed_tools else ""]
    if model:
        cmd += ["--model", model]
    if allowed_tools:
        cmd += ["--allowedTools", ",".join(allowed_tools),
                "--permission-mode", "acceptEdits"]
    try:
        proc = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
            cwd=config.ROOT, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise ClaudeError(f"claude timed out after {timeout}s")
    except FileNotFoundError:
        raise ClaudeError("claude CLI not found on PATH")

    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise ClaudeError(f"claude exit {proc.returncode}: {(proc.stderr or proc.stdout)[:400]}")
    if envelope.get("is_error"):
        raise ClaudeError(f"claude error: {str(envelope.get('result'))[:400]}")
    return envelope


def run_json(prompt, **kw):
    """Run a prompt that must answer with a JSON object. Returns the object."""
    text = run(prompt, **kw).get("result", "")
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ClaudeError(f"no JSON in claude answer: {text[:300]}")
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as err:
        raise ClaudeError(f"bad JSON from claude: {err}")
