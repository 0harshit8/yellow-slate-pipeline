"""Headless Claude Code. Runs `claude -p` in the repo so the project skill is found."""

import json
import re
import subprocess

import config


class ClaudeError(RuntimeError):
    pass


def run(prompt, allowed_tools=None, max_turns=40, timeout=1800):
    """Run one headless session. Returns the parsed --output-format json envelope."""
    cmd = ["claude", "-p", "--output-format", "json", "--max-turns", str(max_turns)]
    if allowed_tools:
        cmd += ["--allowedTools", ",".join(allowed_tools), "--permission-mode", "acceptEdits"]
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
