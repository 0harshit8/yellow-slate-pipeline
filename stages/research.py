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

SHEET_DIR = "research"
INDEX = "index.json"

# A field line: an upper-case key at the start of a line. The review sub-lines ("Academics:
# 80/20") and the numbered THREE_FACTS lines are not upper-case, so they fall through to the
# continuation branch and stay attached to the field above them, which is where they belong.
FIELD = re.compile(r"^([A-Z][A-Z0-9_]*):[ \t]*(.*)$")
# "CURRICULUM: CBSE | source: https://...". The source is what makes a field usable for the
# CRM form later, so it is parsed out rather than left inside the value.
SOURCE = re.compile(r"[ \t]*\|[ \t]*source:[ \t]*(\S+)[ \t]*$", re.I)
FENCE = re.compile(r"^\s*```[a-z]*\s*$|^\s*```\s*$", re.M)

# The sheet's field list, in the agent's own order. Used only to report what a sheet is
# missing; an unexpected extra field is kept, not dropped.
FIELDS = ("SCHOOL", "CMS_ID", "PROFILE_URL", "VERIFIED_VIA", "CURRICULUM", "GRADES",
          "ESTABLISHED", "MEDIUM", "CO_ED", "ADDRESS", "FACILITIES", "FEES", "FEES_SOURCE",
          "FEES_NOTE", "ADMISSIONS", "REVIEWS_BASE", "REVIEWS", "REVIEWS_SOURCE",
          "IMAGE_URL", "THREE_FACTS", "GAPS", "CONFLICTS", "NO_EVIDENCE", "SEARCHES_USED")

# Without these five nobody can verify a created school in their CRM, which is the whole
# reason the sheets are kept. Called out separately so a human reading index.json sees at a
# glance which schools are still unfillable.
CRM_FIELDS = ("CURRICULUM", "MEDIUM", "CO_ED", "GRADES")


def sheet_dir(folder):
    return os.path.join(folder, SHEET_DIR)


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
