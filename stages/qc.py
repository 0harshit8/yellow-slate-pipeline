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


def check_school(name, text, folder):
    issues = []
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
        issues.append("no school image")
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
        if "|" not in fee:
            issues.append("fee section has no table")
        if "source:" not in fee.lower():
            issues.append("fee table has no Source: line")
    return issues


def check_blog(md, keyword, expected_ids=None, folder=None):
    """Returns (passed, [lines]). Each line is 'PASS ...' or 'FAIL ...'."""
    lines, kw = [], keyword.lower()

    def rule(ok, msg):
        lines.append(("PASS " if ok else "FAIL ") + msg)

    title = re.search(r"^#\s+(.+)$", md, re.M)
    rule(bool(title) and kw in title.group(1).lower(), "keyword in H1 title")
    body = md[title.end():] if title else md
    first_para = next((p.strip() for p in re.split(r"\n\s*\n", body) if p.strip() and not p.strip().startswith(("#", "[", "!"))), "")
    rule(kw in first_para.lower(), "keyword in first paragraph")

    blocks = _school_blocks(md)
    rule(len(blocks) >= 1, f"{len(blocks)} school sections found")
    for name, text in blocks:
        issues = check_school(name, text, folder)
        rule(not issues, f"school: {name}" + (f" -> {'; '.join(issues)}" if issues else ""))

    if expected_ids is not None:
        found = {i for i in BTN.findall(md) if i.strip()}
        want = {str(i) for i in expected_ids}
        rule(found == want, "admission IDs match the CMS"
             + ("" if found == want else f" -> missing {sorted(want - found)}, unexpected {sorted(found - want)}"))

    rule(bool(re.search(r"^####\s+.*conclusion", md, re.I | re.M)), "conclusion as H4")
    faq = re.search(r"^#{2,4}\s+.*(faq|frequently asked).*$", md, re.I | re.M)
    n_faq = len(re.findall(r"^(#{2,4}\s+|\*\*|Q[:.]).*\?\**\s*$", md[faq.end():], re.M)) if faq else 0
    rule(n_faq >= 5, f"{n_faq} FAQs, need 5+")

    bad = BAD_LINK.findall(md)
    rule(not bad, "no Edustoke/Ezyschooling hyperlinks")
    bad_links = [l for l in READ_MORE.findall(md) if l != l.lower() or re.search(r"[\s_]", l)]
    rule(not bad_links, "read_more_blogs links lowercase-hyphenated" + (f" -> {bad_links}" if bad_links else ""))
    naked = re.findall(r"(?<![(\"])\bhttps?://\S+", re.sub(r"\[[^\]]*\]\([^)]*\)|\[\w+[^\]]*\]", "", md))
    rule(not naked, "no naked URLs" + (f" -> {naked[:3]}" if naked else ""))

    passed = all(l.startswith("PASS") for l in lines)
    return passed, lines
