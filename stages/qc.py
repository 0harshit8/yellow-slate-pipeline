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
# A third-party directory named in the body. The fact sheets cite these on purpose and must
# keep doing so, but the post is Yellow Slate's own and naming a rival directory in it is
# not what it is for. The board and the government registries are not third parties, so
# CBSE, ICSE, CISCE, UDISE and SARAS are deliberately absent from this list.
NAMED_SOURCE = re.compile(
    r"\b(edustoke|ezyschooling|careers\s?360|educationworld|education\s world|justdial"
    r"|schoolmykids|ambitionbox|uniapply|targetstudy|indiastudychannel|edutribe"
    r"|leverage\s?edu|sulekha|mouthshut|wikipedia|glassdoor|indeed)\b", re.I)
BULLET = re.compile(r"^[ \t]*[-*][ \t]+(.*)$", re.M)
# A fee amount in any form the writer uses. The three-tier fee rule turns on whether one is present.
FEE_AMOUNT = re.compile(r"(?:₹|Rs\.?\s*)\d")
# A review percentage, which the Parent Review section exists to carry.
PERCENT = re.compile(r"\d{1,3}\s?%")
# The fallback sentence, in the shapes the writer produces. Sentences built around it are
# subtracted before a section is judged to have said anything, so a section cannot be made
# of it alone. Its narrow licence survives: an admission section may still use it about this
# year's exact dates, as long as it describes the process too.
FALLBACK = re.compile(r"[^.\n]*contact(?:ing)? the school[^.\n]*\.?", re.I)
# A school count claimed in the title or the description: "for 10 CBSE schools", "the 9 best
# schools", "Top 12 Schools in Kolar". Two digits at most, and never one preceded by a digit
# or a hyphen, because "2026-27" is in every title this pipeline writes and its "27" must not
# read as a count. A number introducing a class is excluded for the same reason. Written as
# digits only: "nine schools" is not checked, which leaves a gap but never invents a failure.
META_COUNT = re.compile(
    r"(?<![\d-])(?<!\bclass )(?<!\bgrade )(?<!\bstd )\b(\d{1,2})\b(?=[^.]{0,30}?\bschools?\b)",
    re.I)


# A fee or a parent review that no source publishes. The section cannot be written, so
# before this such a school could never pass: Hill View Public School (Kalkaji, Oct 2026)
# was looked for on Ezyschooling, Uniapply, Careers360, SchoolsUniverse, SchoolMyKids,
# Justdial, Google Maps, Sulekha, Facebook and MouthShut, had no official site and no
# UDISE record, and carried neither a fee nor a rating.
#
# The escape excuses that one absence and nothing else, and only when notes.md records
# what was tried. This is deliberately not the rule removed on 2026-10-08, which read
# "contact the school" out of the blog body: that rewarded a phrase the writer could type,
# while this asks for research the researcher had to do and write down. It cannot tell a
# true record from an invented one, so it does not try to -- qc_pass still goes to a human,
# and the reason is printed next to the WARN for them to read.
ABSENCE_HEAD = re.compile(r"^#{1,4}\s*documented absences\s*$", re.I | re.M)
ABSENCE_LINE = re.compile(
    r"^[ \t]*[-*][ \t]+(.+?)\s*\|\s*(fee|reviews)\s*\|\s*(.+?)\s*$", re.I | re.M)
# The same floor _substance() uses: a few words are a claim, a sentence is a record.
ABSENCE_REASON_WORDS = 8

# What a declared absence is allowed to excuse. Nothing else in the section is touched, so
# a school with no published fee still needs its Source line, its bullets and its shortcode.
EXCUSED = {
    "fee": ("fee section has no amount",),
    "reviews": ("no parent review graph", "review section has no percentages"),
}


def _norm(name):
    """School names reach QC from the CMS and notes.md from the researcher, which spell
    them differently ('RAM KRISHNA ...' vs 'Ram-Krishna ...')."""
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def slug_links(slug):
    """The two [read_more_blogs] targets a school's CMS slug allows.

    The slug their API returns is "<city>/<school-name>-<locality>", and both table links are
    built straight from it. profile_url() in clients/cms_base.py already does this for the
    first bullet, which is why those links were always right.
    """
    s = str(slug).strip().strip("/")
    return (f"/school/{s}", f"/{s}-reviews")


def _link_key(link):
    """A read_more_blogs link as it compares: no trailing slash, no case, no spaces."""
    return str(link).strip().rstrip("/").lower()


def _slug_list(value):
    """Every slug under one CMS name, from either a bare slug or a list of them.

    A chain puts several campuses in one blog under one CMS name - Bhubaneswar had three
    "DAV Public School" rows. Keyed by name alone they overwrite each other, and the two
    slugs that lost were then read as links to pages that do not exist, failing a blog
    whose links were right. Accepts a bare string so a caller with one slug per name,
    which is every other blog, needs no change.
    """
    values = value if isinstance(value, (list, tuple, set)) else [value]
    return [str(v).strip() for v in values if str(v).strip()]


def absences(notes):
    """{normalised school name: {"fee"|"reviews": reason}} from notes.md.

    Only lines under a "Documented absences" heading count, so prose elsewhere in the file
    excuses nothing, and only lines carrying a reason of real length: a bare "none"
    documents nothing and is ignored.
    """
    if not notes:
        return {}
    head = ABSENCE_HEAD.search(notes)
    if not head:
        return {}
    nxt = re.search(r"^#{1,4}\s", notes[head.end():], re.M)
    block = notes[head.end(): head.end() + nxt.start()] if nxt else notes[head.end():]
    found = {}
    for name, field, reason in ABSENCE_LINE.findall(block):
        if len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'’.-]*", reason)) >= ABSENCE_REASON_WORDS:
            found.setdefault(_norm(name), {})[field.lower()] = reason
    return found


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


def _substance(section, least=8):
    """True when the section says something of its own, not just the fallback sentence.

    Twenty-three published school sections have an Admission Process heading whose whole body
    is "Contact the school for the latest details." The heading was all the old rule asked for.

    The word floor applies only to a section that uses the fallback, so this catches a section
    made of it without also policing a brief real one: "Apply online by 31 January" is short
    and complete, and nothing is gained by failing it.
    """
    words = lambda s: len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'’.-]*", re.sub(r"[-*|#\s]+", " ", s)))
    if not FALLBACK.search(section):
        return words(section) > 0
    return words(FALLBACK.sub("", section)) >= least


def check_school(name, text, folder, slug=None):
    """Returns (issues, warnings). Issues fail QC, warnings only go in qc.txt.

    `slug` is this school's CMS slug, when the run knows it. Both [read_more_blogs] links in
    the info table have to be built from it; see slug_links().
    """
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
    if not graphs:
        issues.append("no parent review graph")
    for _, path in images:
        if path.startswith("http"):
            issues.append(f"image is an external URL, must be a local file: {path}")
        elif folder and not os.path.exists(os.path.join(folder, path)):
            issues.append(f"image file missing: {path}")

    review = _section(text, "review")
    if review is None:
        issues.append("no Parent Review section")
    elif not PERCENT.search(review):
        issues.append("review section has no percentages")

    admission = _section(text, "admission")
    if admission is None:
        issues.append("no Admission Process section")
    elif not _substance(admission):
        issues.append("admission section has no process, only the contact-the-school line")

    fee = _section(text, "fee")
    if fee is None:
        issues.append("no Fee Structure section")
    # Tier 2 is an amount with no class-wise breakdown published, and is allowed to be prose
    # rather than a table. Only a section with no table and no amount at all is a real miss.
    elif "|" not in fee and not FEE_AMOUNT.search(fee):
        issues.append("fee section has no amount")
    elif "source:" not in fee.lower():
        issues.append("fee table has no Source: line")

    # The two table links, against this school's CMS slug. The writer was told to build them
    # from the school's name, which drops the locality the real slug ends in, so all 16 links
    # in the Hyderabad blog pointed at pages that do not exist -- and an unknown slug on their
    # site answers 200 with the homepage, so nothing about them looked broken. String
    # comparison only: QC never goes near the network.
    if slug:
        want = [_link_key(l) for l in slug_links(slug)]
        wrong = sorted({l for l in READ_MORE.findall(text) if _link_key(l) not in want})
        if wrong:
            issues.append(f"read_more_blogs link not built from the CMS slug '{slug}': "
                          f"{wrong}, expected {list(slug_links(slug))}")
    return issues, warnings


def check_blog(md, keyword, expected_ids=None, folder=None, meta=None, notes=None,
               expected_slugs=None):
    """Returns (passed, [lines]). Lines are 'PASS ...', 'FAIL ...' or 'WARN ...' (warnings never fail).

    `expected_slugs` is {CMS name: CMS slug, or a list of them when campuses share a name}
    from the CMS tab, the same rows expected_ids comes
    from. It gates the [read_more_blogs] links, both per school and over the whole post, so a
    link built from the school's name instead of its slug cannot ship again.
    """
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
    declared = absences(notes)
    slugs = {_norm(k): _slug_list(v) for k, v in (expected_slugs or {}).items() if _slug_list(v)}
    for name, text in blocks:
        # One slug only. A name held by several campuses cannot say which is this section's,
        # and the H2 of such a section carries the locality anyway, so it never matched here.
        # The whole-post rule below still checks those links against every slug in the run.
        own = slugs.get(_norm(name)) or []
        issues, warnings = check_school(name, text, folder, own[0] if len(own) == 1 else None)
        # An absence this school declared stops being a failure and becomes a warning
        # carrying its reason, so the human reviewing qc_pass sees what was tried.
        excused = declared.get(_norm(name), {})
        allowed = {msg: field for field in excused for msg in EXCUSED[field]}
        warnings += [f"{i} (documented absence: {excused[allowed[i]]})"
                     for i in issues if i in allowed]
        issues = [i for i in issues if i not in allowed]
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
    named = sorted({n.strip() for n in NAMED_SOURCE.findall(md)}, key=str.lower)
    rule(not named, "no third-party site named in the post"
                    + (f" -> {', '.join(named)}" if named else ""))
    bad_links = [l for l in READ_MORE.findall(md) if l != l.lower() or re.search(r"[\s_]", l)]
    rule(not bad_links, "read_more_blogs links lowercase-hyphenated" + (f" -> {bad_links}" if bad_links else ""))
    # Over the whole post as well as per school. The per-school rule above only fires when the
    # H2 name matches a CMS name, and a writer that spells the H2 its own way would slip past
    # it with every link dead. Here nothing has to match: a read_more_blogs link that is not
    # one of the run's slug links is wrong whichever section it sits in.
    if expected_slugs:
        allowed = {_link_key(l) for v in expected_slugs.values()
                   for s in _slug_list(v) for l in slug_links(s)}
        stray = sorted({l for l in READ_MORE.findall(md) if _link_key(l) not in allowed})
        rule(not stray, "read_more_blogs links match a CMS slug"
             + (f" -> {stray} is no school's /school/<slug> or /<slug>-reviews" if stray else ""))
    naked = re.findall(r"(?<![(\"])\bhttps?://\S+", re.sub(r"\[[^\]]*\]\([^)]*\)|\[\w+[^\]]*\]", "", md))
    rule(not naked, "no naked URLs" + (f" -> {naked[:3]}" if naked else ""))

    passed = not any(l.startswith("FAIL") for l in lines)
    return passed, lines
