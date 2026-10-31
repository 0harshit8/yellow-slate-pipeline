"""Keep the researcher fact sheets a write run collects.

Each school-researcher subagent (.claude/agents/school-researcher.md) returns a fixed field
list -- board, medium, co-ed, grade range, full address, fees, reviews, a photo URL -- each
with the source URL that produced it. Until this module existed the writer used those fields
inline and then dropped them: the only ones that survived a run were the handful blog.md
happens to print.

That cost a measurable amount of work. Schools the pipeline creates in their CMS come out
Verified=No, and a Verified=No school has no public page at all, so all 30 rows in
data/cms_created.log answered 404 on 2026-10-19. Verifying one means filling their CRM form,
whose required fields are School Type, Medium of Instruction, Primary Board, Grade From and
Grade To. Across those 30 rows the board was on disk for 10 and a usable grade range for 9 --
only because blog.md prints a Curriculum and a Grades row -- and medium and co-ed for none,
although every researcher was asked for both. The data existed at research time and was
thrown away before anyone could use it.

So the writer now saves each sheet verbatim under `<run folder>/research/`, and this module
reads that folder after the run and writes `research/index.json`: the same fields parsed,
keyed by CMS id, each with its source URL. The .md files stay as they came back; the index is
only a machine-readable view of them.

Nothing here can fail a run. A sheet that will not parse is kept on disk, reported as a
problem and left out of the index -- losing a finished blog because a fact sheet was malformed
would be a far worse trade than the one this module exists to fix.
"""

import json
import os
import re
import shutil
import time

import config

SHEET_DIR = "research"
INDEX = "index.json"

# The shared store: one sheet per school, named by CMS id, kept across blogs.
#
# A city gets more than one keyword -- "schools in X", "cbse schools in X", "international
# schools in X" -- and 381 of the 483 pending keywords (Oct 2026) sit in a city that has
# another. Every one of them used to re-research every school from scratch, at about 465k
# tokens per school. The sheets were already being saved per run folder; this just puts them
# somewhere the next blog can find them.
STORE_DIR = os.path.join("data", "research")
# Fees are published per session and reviews move slowly, so a sheet is good for a term, not
# a year. Past that it is cheaper to be right than to save the research.
MAX_AGE_DAYS = 90

# A field line: an upper-case key at the start of a line, optionally followed by a qualifier
# in brackets. The researcher writes "FEES (2026-27, tuition per year):" often enough to
# matter, and a key that had to touch the colon turned that line into ordinary text -- which
# silently glued a whole class-wise fee table onto the field above and then reported no FEES.
# The review sub-lines ("Academics: 80/20") and the numbered THREE_FACTS lines are not
# upper-case, so they still fall through to the continuation branch and stay attached to the
# field above them, which is where they belong.
FIELD = re.compile(r"^([A-Z][A-Z0-9_]*)(?:[ \t]*\([^)]*\))?:[ \t]*(.*)$")
# "CURRICULUM: CBSE | source: https://...". The source is what makes a field usable for the
# CRM form later, so it is parsed out rather than left inside the value.
SOURCE = re.compile(r"[ \t]*\|[ \t]*source:[ \t]*(\S+)[ \t]*$", re.I)
FENCE = re.compile(r"^\s*```[a-z]*\s*$|^\s*```\s*$", re.M)

# The sheet's field list, in the agent's own order. Used only to report what a sheet is
# missing; an unexpected extra field is kept, not dropped.
FIELDS = ("SCHOOL", "CMS_ID", "PROFILE_URL", "VERIFIED_VIA", "CURRICULUM", "GRADES",
          "ESTABLISHED", "MEDIUM", "CO_ED", "ADDRESS", "FACILITIES", "FEES", "FEES_SOURCE",
          "FEES_NOTE", "ADMISSIONS", "REVIEWS_BASE", "REVIEWS", "REVIEWS_SOURCE",
          "THREE_FACTS", "GAPS", "CONFLICTS", "NO_EVIDENCE", "SEARCHES_USED")

# Without these five nobody can verify a created school in their CRM, which is the whole
# reason the sheets are kept. Called out separately so a human reading index.json sees at a
# glance which schools are still unfillable.
CRM_FIELDS = ("CURRICULUM", "MEDIUM", "CO_ED", "GRADES")


def sheet_dir(folder):
    return os.path.join(folder, SHEET_DIR)


def store_dir():
    return os.path.join(config.ROOT, STORE_DIR)


def _max_age_days():
    try:
        return max(0, int(config.env("RESEARCH_MAX_AGE_DAYS") or MAX_AGE_DAYS))
    except (TypeError, ValueError):
        return MAX_AGE_DAYS


def reuse(folder, schools, max_age_days=None):
    """Copy any still-fresh stored sheet into this run's research/. Returns the ids reused.

    Called before the writer runs, so a school whose sheet is already on disk needs no
    subagent at all -- which is the saving. The copy lands where collect() and the writer
    both already look, so nothing downstream has to know a sheet was reused.

    Never raises. A store that cannot be read is a run that researches everything, which is
    exactly what used to happen, so there is nothing here worth failing a blog over.
    """
    limit = _max_age_days() if max_age_days is None else max_age_days
    if not limit:
        return set()
    directory = sheet_dir(folder)
    reused = set()
    for s in schools or []:
        sid = str(s.get("id", "")).strip()
        if not sid:
            continue
        src = os.path.join(store_dir(), f"{sid}.md")
        try:
            if not os.path.isfile(src):
                continue
            if (time.time() - os.path.getmtime(src)) > limit * 86400:
                continue
            os.makedirs(directory, exist_ok=True)
            # copy2, not copyfile: a plain copy stamps the new file with today's date, and
            # save_to_store writes that date back to the store -- so a sheet that is reused
            # at all would never reach MAX_AGE_DAYS and never be researched again.
            shutil.copy2(src, os.path.join(directory, f"{sid}.md"))
        except OSError:
            continue
        reused.add(sid)
    return reused


def save_to_store(folder):
    """Copy this run's sheets into the shared store, newest wins. Returns problems.

    A sheet _entry() flags is NOT stored. Storing it would hand the next blog a known-bad
    sheet, and because a stored sheet is marked ALREADY ON DISK no researcher is spawned to
    repair it -- so one bad run would go on producing bad blogs for MAX_AGE_DAYS. Leaving it
    out costs that school one re-research, which is the cheap half of the trade.
    """
    directory, problems = sheet_dir(folder), []
    if not os.path.isdir(directory):
        return problems
    try:
        os.makedirs(store_dir(), exist_ok=True)
    except OSError as err:
        return [f"research store not created ({err})"]
    for name in sorted(os.listdir(directory)):
        if not name.lower().endswith(".md"):
            continue
        path = os.path.join(directory, name)
        try:
            with open(path, encoding="utf-8") as fh:
                _, flaw = _entry(path, fh.read())
        except OSError as err:
            problems.append(f"{name}: not stored for reuse ({err})")
            continue
        if flaw:
            problems.append(f"{name}: not stored for reuse, it would be cached as-is ({flaw})")
            continue
        try:
            # copy2 for the same reason as in reuse(): the mtime IS the sheet's age.
            shutil.copy2(path, os.path.join(store_dir(), name))
        except OSError as err:
            problems.append(f"{name}: not stored for reuse ({err})")
    return problems


def parse_sheet(text):
    """One fact sheet -> {"FIELD": {"value": str, "source": str|None}} in sheet order.

    Deliberately forgiving. The sheet is markdown written by a model, so it may arrive inside
    a code fence, with a stray preamble, or with only half its fields. Anything that looks
    like `KEY: value` is taken; anything else is appended to the field above it. A sheet with
    no field lines at all returns {}, which is how the caller tells malformed from partial.
    """
    fields, key = {}, None
    for line in FENCE.sub("", str(text or "")).splitlines():
        match = FIELD.match(line)
        if match:
            key = match.group(1)
            value = match.group(2)
            source = SOURCE.search(value)
            fields[key] = {"value": SOURCE.sub("", value).strip() if source else value.strip(),
                           "source": source.group(1) if source else None}
        elif key and line.strip():
            # A continuation: the review categories, the three facts, a wrapped GAPS line.
            fields[key]["value"] = (fields[key]["value"] + "\n" + line.strip()).strip()
            if not fields[key]["source"]:
                source = SOURCE.search(line)
                if source:
                    fields[key]["source"] = source.group(1)
                    fields[key]["value"] = SOURCE.sub("", fields[key]["value"]).strip()
    return fields


def _entry(path, text):
    fields = parse_sheet(text)
    rel = os.path.join(SHEET_DIR, os.path.basename(path)).replace("\\", "/")
    if not fields:
        return None, f"{rel}: no fields parsed, sheet kept as it came back"
    def value(name):
        return (fields.get(name) or {}).get("value", "")
    entry = {
        "cms_id": value("CMS_ID") or os.path.splitext(os.path.basename(path))[0],
        "school": value("SCHOOL"),
        "file": rel,
        "fields": fields,
        "missing": [f for f in FIELDS if f not in fields],
        "crm_missing": [f for f in CRM_FIELDS
                        if not value(f) or value(f).upper() in ("OMIT", "NOT_FOUND", "NONE")],
    }
    problem = None
    if entry["missing"]:
        problem = f"{rel}: partial sheet, no {', '.join(entry['missing'])}"
    return entry, problem


def collect(folder, schools=None):
    """Read `<folder>/research/*.md` and write `research/index.json`. Returns problems.

    `schools` is the list build_prompt was given, used only to say which schools have no
    sheet on disk at all. Never raises: every failure comes back as a line in the problem
    list, which the write stage prints alongside the asset problems.
    """
    out, problems = [], []
    directory = sheet_dir(folder)
    paths = sorted(os.path.join(directory, n) for n in os.listdir(directory)
                   if n.lower().endswith(".md")) if os.path.isdir(directory) else []
    for path in paths:
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        except OSError as err:
            problems.append(f"{os.path.basename(path)}: not read ({err})")
            continue
        entry, problem = _entry(path, text)
        if problem:
            problems.append(problem)
        if entry:
            out.append(entry)

    saved = {str(e["cms_id"]).strip() for e in out}
    # Named by the id the file was named with as well as the id parsed out of it, so a school
    # whose sheet is on disk but unparseable is told apart from one whose sheet never arrived.
    on_disk = {os.path.splitext(os.path.basename(p))[0].strip() for p in paths}
    for s in schools or []:
        sid = str(s.get("id", "")).strip()
        if sid in saved:
            continue
        what = "its sheet did not parse" if sid in on_disk else f"no fact sheet in {SHEET_DIR}/"
        problems.append(f"{s.get('name')} ({s.get('id')}): {what}, so its medium, co-ed and "
                        f"address are not on disk")
    if not paths:
        problems.append(f"no fact sheets in {SHEET_DIR}/ -- the writer saved none of them")

    if out or paths:
        os.makedirs(directory, exist_ok=True)
        try:
            with open(os.path.join(directory, INDEX), "w", encoding="utf-8") as fh:
                json.dump({"schools": out}, fh, indent=2, ensure_ascii=False)
        except OSError as err:
            problems.append(f"{SHEET_DIR}/{INDEX} not written ({err})")
    return problems
