"""Stage 5: deterministic checks before Harshit reviews a blog.

Covers what Vindhya kept flagging in QC plus the skill's own hard rules.
It can't judge tone or facts. That stays with the human review.
"""

import os
import re

H2_SCHOOL = re.compile(r"^##\s+\d+\.\s+(.+)$", re.M)
BTN = re.compile(r'\[btn_admissions\s+id="([^"]*)"\]')
IMG = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)")
READ_MORE = re.compile(r'\[read_more_blogs\s+link="([^"]*)"')
BAD_LINK = re.compile(r"\]\([^)]*(edustoke|ezyschooling)[^)]*\)", re.I)
BULLET = re.compile(r"^[ \t]*[-*][ \t]+(.*)$", re.M)
# A fee amount in any form the writer uses. The three-tier fee rule turns on whether one is present.
FEE_AMOUNT = re.compile(r"(?:₹|Rs\.?\s*)\d")
# A school count claimed in the title or the description: "for 10 CBSE schools", "the 9 best
# schools", "Top 12 Schools in Kolar". Two digits at most, and never one preceded by a digit
# or a hyphen, because "2026-27" is in every title this pipeline writes and its "27" must not
# read as a count. A number introducing a class is excluded for the same reason. Written as
# digits only: "nine schools" is not checked, which leaves a gap but never invents a failure.
META_COUNT = re.compile(
    r"(?<![\d-])(?<!\bclass )(?<!\bgrade )(?<!\bstd )\b(\d{1,2})\b(?=[^.]{0,30}?\bschools?\b)",
    re.I)


def _school_blocks(md):
    """[(name, text)] for each '## N. School' section, cut before the conclusion / FAQ."""
    marks = list(H2_SCHOOL.finditer(md))
    blocks = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(md)
        text = md[m.start():end]
        tail = re.search(r"^(####\s|##\s+(?!\d+\.)).*$", text[3:], re.M)
        if tail:
            text = text[:tail.start() + 3]
        blocks.append((m.group(1).strip(), text))
    return blocks


def _section(text, word):
    """Body of the first ### heading containing word, up to the next heading."""
    m = re.search(rf"^###\s+.*{word}.*$", text, re.I | re.M)
    if not m:
        return None
    nxt = re.search(r"^#{2,4}\s", text[m.end():], re.M)
    return text[m.end(): m.end() + nxt.start()] if nxt else text[m.end():]


def word_budget(n_schools):
    """The skill's length formula, in one place. stages/write.py puts this number in the
    prompt and the length check below gates on it, so the writer's target and QC's gate
    can't drift apart."""
    return 300 * n_schools + 900


def word_count(md):
    """Prose words a reader sees: shortcodes, image lines and comments don't count."""
    body = re.sub(r"<!--.*?-->", "", md, flags=re.S)
    body = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", body)
    body = re.sub(r"\[(?:btn_admissions|read_more_blogs)[^\]]*\]", "", body)
    body = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", body)  # keep link text, drop the URL
    return len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'’.-]*", body))


def meta_school_counts(meta):
    """Every school count the title, meta title or description claims. [] when none does.

    The fields are joined with a full stop so the lookahead cannot read "schools" out of the
    next field and pin it on a number in this one.
    """
    text = " . ".join(str(meta.get(k, "")) for k in ("title", "meta_title", "meta_description"))
    return [int(n) for n in META_COUNT.findall(text)]


def check_school(name, text, folder):
    """Returns (issues, warnings). Issues fail QC, warnings only go in qc.txt."""
    issues, warnings = [], []
    btn = BTN.search(text)
    if not btn:
        issues.append("no [btn_admissions] shortcode")
    elif not btn.group(1).strip():
        issues.append("empty btn_admissions id")

    # Intro bullets: after the shortcode, before the first image or table.
    start = btn.end() if btn else 0
    stop = min([p for p in (text.find("![", start), text.find("\n|", start)) if p != -1] or [len(text)])
    bullets = [b for b in BULLET.findall(text[start:stop])]
    if len(bullets) != 3:
        issues.append(f"{len(bullets)} intro bullets, need exactly 3")
    elif not bullets[0].lstrip("*").startswith("["):
        issues.append("first bullet doesn't start with the linked school name")

    images = IMG.findall(text)
    graphs = [i for i in images if "graph" in i[1].lower() or "sentiment" in i[0].lower()]
    photos = [i for i in images if i not in graphs]
    if not photos:
        warnings.append("no school image (allowed if none found, check notes.md)")
    if not graphs:
        issues.append("no parent review graph")
    for _, path in images:
        if path.startswith("http"):
            issues.append(f"image is an external URL, must be a local file: {path}")
        elif folder and not os.path.exists(os.path.join(folder, path)):
            issues.append(f"image file missing: {path}")

    if _section(text, "review") is None:
        issues.append("no Parent Review section")
    if _section(text, "admission") is None:
        issues.append("no Admission Process section")
    fee = _section(text, "fee")
    if fee is None:
        issues.append("no Fee Structure section")
    elif "contact the school" not in fee.lower():
        # Tier 2 is an amount with no class-wise breakdown published, and is allowed to be prose
        # rather than a table. Only a section with no table and no amount at all is a real miss.
        if "|" not in fee and not FEE_AMOUNT.search(fee):
            issues.append("fee section has no table")
        if "source:" not in fee.lower():
            issues.append("fee table has no Source: line")
    return issues, warnings


def check_blog(md, keyword, expected_ids=None, folder=None, meta=None):
    """Returns (passed, [lines]). Lines are 'PASS ...', 'FAIL ...' or 'WARN ...' (warnings never fail)."""
    lines, kw = [], keyword.lower()

    def rule(ok, msg):
        lines.append(("PASS " if ok else "FAIL ") + msg)

    # Their spec: no heading above the intro. The title lives in meta.json.
    rule(not re.search(r"^#\s", md, re.M), "no H1 in the blog body")
    if meta is not None:
        rule(kw in str(meta.get("title", "")).lower() and kw in str(meta.get("meta_title", "")).lower(),
             "keyword in title and meta title")
        rule(bool(str(meta.get("meta_description", "")).strip()), "meta description present")
    first_para = next((p.strip() for p in re.split(r"\n\s*\n", md) if p.strip() and not p.strip().startswith(("#", "[", "!"))), "")
    rule(kw in first_para.lower(), "keyword in first paragraph")

    blocks = _school_blocks(md)
    rule(len(blocks) >= 1, f"{len(blocks)} school sections found")

    # A count in the meta is a promise to the reader and to Google, and dropping a school by
    # hand after a write run leaves it stale: the Kolar post went out offering ten schools
    # over nine sections, and every other meta rule passed because they only ask whether a
    # description is present. Only checked when a count is actually claimed.
    if meta is not None:
        claimed = sorted(set(meta_school_counts(meta)))
        wrong = [c for c in claimed if c != len(blocks)]
        if claimed:
            rule(not wrong, "meta school count matches the post" + (
                f" -> meta says {', '.join(str(c) for c in wrong)}, the post has {len(blocks)}"
                if wrong else ""))
    for name, text in blocks:
        issues, warnings = check_school(name, text, folder)
        rule(not issues, f"school: {name}" + (f" -> {'; '.join(issues)}" if issues else ""))
        lines.extend(f"WARN school: {name} -> {w}" for w in warnings)

    if expected_ids is not None:
        found = {i for i in BTN.findall(md) if i.strip()}
        want = {str(i) for i in expected_ids}
        rule(found == want, "admission IDs match the CMS"
             + ("" if found == want else f" -> missing {sorted(want - found)}, unexpected {sorted(found - want)}"))

    rule(bool(re.search(r"^####\s+.*conclusion", md, re.I | re.M)), "conclusion as H4")
    faq = re.search(r"^#{2,4}\s+.*(faq|frequently asked).*$", md, re.I | re.M)
    n_faq = len(re.findall(r"^(#{2,4}\s+|\*\*|Q[:.]).*\?\**\s*$", md[faq.end():], re.M)) if faq else 0
    rule(n_faq >= 5, f"{n_faq} FAQs, need 5+")

    # The writer used to shell out to Measure-Object to check its own length. It has no
    # shell now, so the budget is checked here instead. The prompt now carries the same
    # number (stages/write.py), so this gates on a target the writer was actually given.
    # The seven blogs written before the budget was in the prompt ran 1.36-1.65x, so 1.5x
    # fails and 1.25x warns. Tighten both once runs that had the number show what it holds.
    words = word_count(md)
    budget = word_budget(len(blocks))
    ratio = words / budget if budget else 0
    rule(ratio <= 1.5, f"{words:,} words, {ratio:.2f}x the ~{budget:,} word budget")
    if 1.25 < ratio <= 1.5:
        lines.append(f"WARN length: {ratio:.2f}x budget, trim toward 250-300 words per school")

    bad = BAD_LINK.findall(md)
    rule(not bad, "no Edustoke/Ezyschooling hyperlinks")
    bad_links = [l for l in READ_MORE.findall(md) if l != l.lower() or re.search(r"[\s_]", l)]
    rule(not bad_links, "read_more_blogs links lowercase-hyphenated" + (f" -> {bad_links}" if bad_links else ""))
    naked = re.findall(r"(?<![(\"])\bhttps?://\S+", re.sub(r"\[[^\]]*\]\([^)]*\)|\[\w+[^\]]*\]", "", md))
    rule(not naked, "no naked URLs" + (f" -> {naked[:3]}" if naked else ""))

    passed = not any(l.startswith("FAIL") for l in lines)
    return passed, lines
