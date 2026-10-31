"""Find the three fields a browser has to fetch, and merge the answers back.

The headless researcher gets most of a fact sheet right. Three fields it cannot get at all:
Justdial answers a direct fetch with 403, some fee tables are published only as scans, and
deciding whether a photograph shows the building or a prize-giving needs eyes. So this is a
repair pass over three fields, not a second research pass. See BROWSER_TOPUP.md.

It is split from the browser half on purpose. clients/claude_cli.py runs every LLM step as
`claude -p --strict-mcp-config`, which skips MCP servers -- the browser among them -- so the
browser work has to happen in a desktop session instead. worklist() and apply_patch() are
plain Python with no LLM and no browser, and the two halves meet at JSON. That also makes
the risky half, the one that rewrites a stored sheet, testable on its own.
"""

import json
import os
import re
import time

from stages import research

# A field that needs a browser says so, either by being absent or by carrying one of these.
# BLOCKED is the researcher saying "this exists and I was refused"; NOT_FOUND is "I looked
# and there is nothing". Both end up here, because a NOT_FOUND from a tool that cannot read
# Justdial is not evidence of absence -- measured on Gwalior, six of twelve.
EMPTY = ("", "NOT_FOUND", "NONE", "OMIT", "BLOCKED")
# A fee note that admits the real table was unreadable. The value can still hold aggregator
# figures, so the field alone does not show the gap.
UNREADABLE = re.compile(r"\b(scan|scanned|unreadable|image[- ]based"
                        r"|(?:will|would|could|does|did) ?n[o']t render"
                        r"|could ?n[o']t (?:be )?(?:read|open(?:ed)?))\b", re.I)

FIELD_FOR = {"reviews": "REVIEWS", "fees": "FEES", "image": "IMAGE_URL"}

# The ceiling for one run's photo hunt: 3,000,000 tokens, which is the number the user set.
# Nothing here can count real tokens -- a subagent's usage never comes back to the pipeline
# -- so the budget is spent in the unit this module can count: schools sent to a browser for
# a photo. From BROWSER_TOPUP.md s6, measured over 14 topper agents: ~68,000 tokens to start
# an agent, four schools sharing one start, ~630 a tool call, and a photo takes about eight
# calls (list, open, look, record). The headless researcher's share of the same hunt -- one
# extra fetch and at most one extra search, ~40,000 against its ~465,000 a school -- is
# counted here too, because the two halves are hunting the same photo.
#
# At ~62,000 a school that is about 48 schools, or four blogs' worth, in one run. A single
# blog is 8-12 schools and never reaches it; a city sweep across several keywords does.
IMAGE_BUDGET = 3_000_000
IMAGE_COST = 40_000 + 68_000 // 4 + 630 * 8


def image_cap(budget=IMAGE_BUDGET):
    """How many schools one run may send looking for a photo before the budget is spent."""
    return max(0, int(budget // IMAGE_COST))


def _value(fields, name):
    return str((fields.get(name) or {}).get("value", "")).strip()


def _head(value):
    """'BLOCKED | https://...' -> 'BLOCKED'. The marker is the first word before any pipe.

    Researchers routinely write the marker and then explain themselves in the same field --
    'NONE (the site has unlabelled images)', 'NOT_FOUND for Dal Bazar'. Taking the whole
    string missed those and left schools out of the worklist, so stop at the first word.
    """
    head = value.split("|", 1)[0].strip()
    return re.split(r"[\s.,;:(]", head, maxsplit=1)[0].strip().upper()


def _url(value):
    """The url a BLOCKED field parked for us, if it left one."""
    after = value.split("|", 1)[1].strip() if "|" in value else ""
    match = re.search(r"https?://\S+", after or value)
    return match.group(0) if match else ""


def topped_up(fields):
    """The field names a browser pass has already filled, from the sheet's TOPUP line."""
    value = _value(fields, "TOPUP")
    return {f.strip().upper() for f in value.split("|")[-1].split(",") if f.strip()} if value else set()


def needs(fields):
    """Which of reviews/fees/image this parsed sheet still needs a browser for."""
    out, done = [], topped_up(fields)
    for group, name in FIELD_FOR.items():
        value = _value(fields, name)
        if name not in fields or _head(value) in EMPTY:
            out.append(group)
        elif group == "fees" and "FEES" not in done and UNREADABLE.search(_value(fields, "FEES_NOTE")):
            # fees are present but came off an aggregator because the school's own table
            # would not render. The browser can read the real one.
            out.append(group)
    return out


def spend_image_budget(work, left):
    """Drop the image group past the run's photo budget. Returns (work, budget left, dropped).

    Reviews and fees are never dropped -- they are what this pass exists for, and a photo
    can be added by hand. An entry left with nothing to do leaves the worklist, so a browser
    session is never started for a school it has no work on.
    """
    dropped = 0
    for w in work:
        if "image" not in w["needs"]:
            continue
        if left > 0:
            left -= 1
        else:
            w["needs"].remove("image")
            w["urls"].pop("image", None)
            dropped += 1
    return [w for w in work if w["needs"]], left, dropped


def sheet_path(cms_id):
    return os.path.join(research.store_dir(), f"{str(cms_id).strip()}.md")


def worklist(schools):
    """[{id, name, city, area, needs, urls}] for schools whose stored sheet has gaps.

    A school with no stored sheet at all is not a top-up, it is research, so it comes back
    under "no sheet" for the caller to report rather than silently as work.
    """
    work, missing = [], []
    for s in schools:
        cms_id = str(s.get("id", "")).strip()
        if not cms_id:
            continue
        path = sheet_path(cms_id)
        try:
            with open(path, encoding="utf-8") as fh:
                fields = research.parse_sheet(fh.read())
        except OSError:
            missing.append(s.get("name") or cms_id)
            continue
        gaps = needs(fields)
        if not gaps:
            continue
        work.append({
            "id": cms_id,
            "name": s.get("name") or _value(fields, "SCHOOL"),
            "city": s.get("city", ""),
            "area": s.get("area") or "",
            "sheet": path,
            "needs": gaps,
            "urls": {g: _url(_value(fields, FIELD_FOR[g])) for g in gaps
                     if _url(_value(fields, FIELD_FOR[g]))},
            "profile": _value(fields, "PROFILE_URL"),
        })
    return work, missing


def _render(name, value):
    value = str(value).rstrip()
    # REVIEWS carries its categories on indented lines below the key, so a value that starts
    # with a newline has to stay flush against the colon.
    return f"{name}:{value}" if value.startswith("\n") else f"{name}: {value}"


def _blocks(lines):
    """[(name, start, end)] over the sheet's field blocks. end is exclusive."""
    heads = [(i, m.group(1)) for i, line in enumerate(lines)
             if (m := research.FIELD.match(line))]
    return [(name, i, heads[n + 1][0] if n + 1 < len(heads) else len(lines))
            for n, (i, name) in enumerate(heads)]


def patch_text(text, patch):
    """Replace just these fields in a sheet, leaving every other byte alone.

    A field already in the sheet is rewritten in place, keeping the blank lines that
    followed it so the file's shape survives. One that is not there is appended; order does
    not matter to parse_sheet, and appending cannot disturb what is already correct.
    """
    lines = text.splitlines()
    for name, start, end in reversed(_blocks(lines)):
        if name not in patch:
            continue
        block, tail = lines[start:end], []
        while block and not block[-1].strip():
            tail.insert(0, block.pop())
        lines[start:end] = _render(name, patch[name]).splitlines() + tail
    seen = {name for name, _, _ in _blocks(lines)}
    for name, value in patch.items():
        if name not in seen:
            lines += ["", _render(name, value)]
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def apply_patch(path, patch, now=None):
    """Merge a browser patch into a stored sheet. Returns (changed_fields, problem).

    Refuses to write when the result would not parse, or when a field nobody patched came
    out different. The sheet on disk is the only copy of research that cost real money, and
    a bad merge would be cached for MAX_AGE_DAYS before anyone noticed.
    """
    patch = {k.strip().upper(): v for k, v in (patch or {}).items() if str(v).strip()}
    if not patch:
        return [], None
    try:
        with open(path, encoding="utf-8") as fh:
            before_text = fh.read()
    except OSError as err:
        return [], f"{os.path.basename(path)}: not read ({err})"

    before = research.parse_sheet(before_text)
    stamp = time.strftime("%Y-%m-%d", time.localtime(now)) if now else time.strftime("%Y-%m-%d")
    # TOPUP accumulates. A later pass that fixes one field must not erase the record of an
    # earlier one, or needs() offers that field up for a second paid browser run.
    patch["TOPUP"] = f"{stamp} | {', '.join(sorted(topped_up(before) | set(patch)))}"
    after_text = patch_text(before_text, patch)
    after = research.parse_sheet(after_text)

    if not after:
        return [], f"{os.path.basename(path)}: patch would leave an unparseable sheet"
    for name, field in before.items():
        if name in patch:
            continue
        if (after.get(name) or {}).get("value") != field.get("value"):
            return [], (f"{os.path.basename(path)}: patch changed {name}, which it does not "
                        f"own -- nothing written")
    for name in patch:
        if name not in after:
            return [], f"{os.path.basename(path)}: {name} did not survive the patch"

    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(after_text)
    except OSError as err:
        return [], f"{os.path.basename(path)}: not written ({err})"
    return sorted(k for k in patch if k != "TOPUP"), None


def read_patches(path):
    """{cms_id: {FIELD: value}} from the browser half's JSON. Never raises."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as err:
        raise ValueError(f"{path}: {err}") from err
    if isinstance(data, list):       # [{"id": ..., "fields": {...}}]
        return {str(d.get("id", "")).strip(): d.get("fields") or {} for d in data}
    return {str(k).strip(): v for k, v in (data or {}).items()}
