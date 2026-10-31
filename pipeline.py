#!/usr/bin/env python
"""
Yellow Slate 600-blog pipeline. The Google Sheet is the control center.

Flow per keyword (Blogs tab Status column):
  new -> pick -> picked -> [Harshit ticks schools, sets approved] -> cms -> cms_done
      -> write -> written -> qc -> qc_pass | qc_fail -> draft (unpublished, Live link set)
      -> [Harshit reviews in their CMS + publishes] -> published

Commands
--------
  python pipeline.py setup                       build/refresh the sheet tabs (safe to re-run)
  python pipeline.py add "<kw>" ["<kw>" ...] --city C [--area A]   add keyword rows (duplicates skipped)
  python pipeline.py pick   [--limit N] [--row KEYWORD]
  python pipeline.py cms    [--limit N] [--row KEYWORD]
  python pipeline.py write  [--limit N] [--row KEYWORD]
  python pipeline.py qc     [--limit N] [--row KEYWORD]
  python pipeline.py draft  --row KEYWORD            unpublished draft in their CMS + edit link
  python pipeline.py topup  [--row KEYWORD] [--apply FILE]
                                                 which schools still need a browser (reviews,
                                                 scanned fee tables, building photos), and
                                                 merge back what a browser session found
  python pipeline.py names                       Semrush paste list (bare school names, 100 per batch)
  python pipeline.py volumes                     fill Vol from Semrush exports in data/semrush/
  python pipeline.py docx   [--row KEYWORD]       rebuild blog.docx (to share) from blog.md
  python pipeline.py show   [--row KEYWORD]       numbered school list for picked blogs
  python pipeline.py approve --row KEYWORD --schools "1-12 drop 4,7"   tick those, set approved
  python pipeline.py setvol --row KEYWORD --vols "1:320, 2:90"   volumes typed in or read off a screenshot
  python pipeline.py suggest [--row KEYWORD]    schools chosen by the volume rule (100+, max 12, top up to 8)
  python pipeline.py status

--row can be given more than once to cover several keywords.

Each stage only takes rows in the status before it. A failed row keeps its status and
gets an Error note, so rerunning the stage retries just the failures.
"""

import argparse
import json
import os
import re
import sys
from collections import Counter

import config
from clients import sheet
from clients.claude_cli import ClaudeError
from clients.cms_base import CMSError, get_cms
from clients.tavily import TavilyError
from stages import cms as cms_stage
from stages import pick as pick_stage
from stages import qc as qc_stage
from stages import topup as topup_stage
from stages import write as write_stage
from stages.names import blog_slug, semrush_term
from stages.selection import new_keywords, parse_selection, parse_vols, suggest_schools
from stages.semrush import semrush_volumes

SEMRUSH_DIR = os.path.join(config.DATA_DIR, "semrush")

# How many schools a published listicle needs. The CMS stage drops a school whose area it
# cannot resolve, so a blog can fall below the minimum after ticking and has to stop.
MIN_SCHOOLS, MAX_SCHOOLS = 8, 12

def area_from_keyword(keyword):
    m = re.search(r"\bin\s+(.+)$", keyword, re.I)
    return m.group(1).strip().title() if m else ""


def wanted(args):
    return {r.strip().lower() for r in args.row}


def mine(blogs):
    """Only this machine's rows when WRITER is set in .env, so two writers never take the same keyword."""
    if not config.WRITER:
        return blogs
    return [b for b in blogs if b.get("Writer", "").strip().lower() == config.WRITER.lower()]


def rows_in(blogs, status, args):
    rows = [b for b in mine(blogs) if b["Status"].strip() == status]
    if args.row:
        rows = [b for b in rows if b["Keyword"].strip().lower() in wanted(args)]
    limit = getattr(args, "limit", 0)
    return rows[:limit] if limit else rows


def approved_schools(picks, keyword):
    """Ticked schools for a blog, in the order they appear in its block."""
    block = picks.get(keyword.strip().lower())
    return [s for s in block["schools"] if s["approved"]] if block else []


def cms_rows(cms_records, keyword):
    return [r for r in cms_records if r["Keyword"].strip().lower() == keyword.strip().lower()]


def blog_folder(b):
    return os.path.join(config.OUTPUT_DIR, b["Slug"] or blog_slug(b["Keyword"], b["City"]))


# --------------------------------------------------------------------------- #


def cmd_setup(sh, args):
    sheet.setup(sh)
    print("Sheet ready: Blogs, Schools, CMS, Weekly review.")


def cmd_add(sh, args):
    ws = sh.worksheet(sheet.BLOGS)
    fresh, skipped = new_keywords([b["Keyword"] for b in sheet.records(ws)], args.keyword)
    if args.area and len(fresh) > 1:
        sys.exit("--area only works with one keyword; leave it out and the area comes from each keyword")
    rows = []
    for kw in fresh:
        area = args.area or area_from_keyword(kw)
        rows.append(["", kw, "", args.city, area, blog_slug(kw, args.city), "new", "", "", "", ""])
        print(f"Added: {kw} | {args.city} | {area}")
    if rows:
        sheet.append(ws, rows)
    for kw in skipped:
        print(f"Skipped, already in the sheet: {kw}")


def cmd_pick(sh, args):
    blogs_ws, schools_ws = sh.worksheet(sheet.BLOGS), sh.worksheet(sheet.SCHOOLS)
    for b in rows_in(sheet.records(blogs_ws), "new", args):
        kw = b["Keyword"].strip()
        print(f"pick: {kw}")
        try:
            shortlist, n_pages = pick_stage.candidates(kw, b["City"])
            if not shortlist:  # Tavily extract or Claude sometimes comes back empty once; retry
                print("  empty result, retrying once")
                shortlist, n_pages = pick_stage.candidates(kw, b["City"])
        except (TavilyError, ClaudeError) as err:
            sheet.set_blog(blogs_ws, b["_row"], error=f"pick: {err}")
            print(f"  error: {err}")
            continue
        if not shortlist:
            why = "no competitor pages could be read" if not n_pages else f"read {n_pages} pages but found no school lists"
            sheet.set_blog(blogs_ws, b["_row"], error=f"pick: {why}")
            print(f"  {why}")
            continue
        sheet.write_pick(schools_ws, kw, shortlist)
        os.makedirs(blog_folder(b), exist_ok=True)
        with open(os.path.join(blog_folder(b), "pick.json"), "w", encoding="utf-8") as fh:
            json.dump(shortlist, fh, indent=2)
        sheet.set_blog(blogs_ws, b["_row"], status="picked")
        print(f"  {len(shortlist)} schools from {n_pages} pages. Top: "
              + ", ".join(f"{s['name']} ({s['count']})" for s in shortlist[:5]))


def cmd_names(sh, args):
    """Paste-ready list of bare school names that still need a volume, 100 per Semrush batch."""
    blogs = {b["Keyword"].strip().lower(): b for b in sheet.records(sh.worksheet(sheet.BLOGS))}
    terms = []
    for key, block in sheet.read_picks(sh.worksheet(sheet.SCHOOLS)).items():
        b = blogs.get(key, {})
        for s in block["schools"]:
            if not s["volume"]:
                terms.append(semrush_term(s["name"], b.get("Area", ""), b.get("City", "")))
    terms = sorted(set(t for t in terms if t))
    if not terms:
        print("Every school already has a volume.")
        return
    os.makedirs(SEMRUSH_DIR, exist_ok=True)
    path = os.path.join(config.DATA_DIR, "semrush_list.txt")
    chunks = [terms[i:i + 100] for i in range(0, len(terms), 100)]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n\n".join("\n".join(c) for c in chunks) + "\n")
    print(f"{len(terms)} names in {len(chunks)} batch(es) of up to 100, saved to {path}\n")
    for i, c in enumerate(chunks, 1):
        print(f"--- batch {i} ---")
        print("\n".join(c))
    print(f"\nSemrush: Keyword Overview -> bulk, database India, paste a batch, export, "
          f"save the file into {SEMRUSH_DIR}, then run: python pipeline.py volumes")


def cmd_volumes(sh, args):
    """Fill the Vol column from Semrush exports in data/semrush/."""
    found = semrush_volumes(SEMRUSH_DIR)
    if not found:
        sys.exit(f"No Semrush exports with Keyword + Volume columns in {SEMRUSH_DIR}")
    blogs = {b["Keyword"].strip().lower(): b for b in sheet.records(sh.worksheet(sheet.BLOGS))}
    ws = sh.worksheet(sheet.SCHOOLS)
    cells, missing = [], []
    for key, block in sheet.read_picks(ws).items():
        b = blogs.get(key, {})
        for s in block["schools"]:
            if s["volume"]:
                continue
            term = semrush_term(s["name"], b.get("Area", ""), b.get("City", ""))
            if term in found:
                cells.append((s["row"], found[term]))
            else:
                missing.append(term)
    sheet.set_volumes(ws, cells)
    print(f"Filled {len(cells)} volumes from {len(found)} Semrush keywords.")
    if missing:
        print(f"{len(set(missing))} not in the exports yet: " + ", ".join(sorted(set(missing))[:20]))


def cmd_cms(sh, args):
    blogs_ws, cms_ws = sh.worksheet(sheet.BLOGS), sh.worksheet(sheet.CMS)
    cms = get_cms()
    picks = sheet.read_picks(sh.worksheet(sheet.SCHOOLS))
    done = sheet.records(cms_ws)
    for b in rows_in(sheet.records(blogs_ws), "approved", args):
        kw, city, area = b["Keyword"].strip(), b["City"].strip(), b["Area"].strip()
        picked = approved_schools(picks, kw)
        if not city or not area:
            sheet.set_blog(blogs_ws, b["_row"], error="cms: City and Area must be filled")
            continue
        if not MIN_SCHOOLS <= len(picked) <= MAX_SCHOOLS:
            sheet.set_blog(blogs_ws, b["_row"], error=f"cms: {len(picked)} schools ticked, need {MIN_SCHOOLS}-{MAX_SCHOOLS}")
            print(f"cms: {kw}: {len(picked)} ticked, skipped")
            continue
        print(f"cms: {kw}")
        have = {r["School"].strip().lower() for r in cms_rows(done, kw) if r["CMS ID"].strip()}
        new_rows, failed, skipped = [], None, []
        for s in picked:
            if s["name"].lower() in have:
                continue  # done on an earlier run
            # The area is the school's own locality, never the keyword's. A city keyword like
            # "best schools in Lucknow" has no single area, and area=city is an empty area in
            # their CMS, so using it would create a duplicate of every school. Their search
            # reports each school's real area, so ensure_school only has to work one out when
            # the name is shared or the school is new. See stages/cms.py and stages/area.py.
            try:
                res = cms_stage.ensure_school(cms, s["name"], city,
                                              page_area=s.get("area", ""), blog_area=area)
            except cms_stage.UnplaceableSchool as err:
                skipped.append(str(err))
                print(f"  skipped {err}")
                continue
            except CMSError as err:
                failed = err
                break
            except Exception as err:
                # A CMS client that doesn't wrap its own errors must not kill the whole batch.
                failed = f"{type(err).__name__}: {err}"
                break
            school_area = res.get("area", "")
            new_rows.append([kw, s["name"], res["name"], res["id"], res["slug"],
                             "y" if res["created"] else "n", school_area])
            flag = " REVIEW" if res.get("review") else ""
            print(f"  {'created' if res['created'] else 'exists '} {res['id']} "
                  f"{res['name']} [{school_area}] {res.get('note', '')}{flag}")
        if new_rows:
            sheet.append(cms_ws, new_rows)  # keep what succeeded, even if a later school failed
        if failed:
            sheet.set_blog(blogs_ws, b["_row"], error=f"cms: {failed}")
            print(f"  error: {failed}")
            continue
        # A skipped school is dropped from the blog, so the post can fall under the 8 it needs.
        resolved = len([s for s in picked if s["name"].lower() in have]) + len(new_rows)
        if resolved < MIN_SCHOOLS:
            why = f"cms: only {resolved} of {len(picked)} schools could be placed. " \
                  f"Fill the Area column for: {'; '.join(skipped)}"
            sheet.set_blog(blogs_ws, b["_row"], error=why[:450])
            print(f"  error: {why}")
            continue
        if skipped:
            sheet.set_blog(blogs_ws, b["_row"], error=f"cms: dropped {len(skipped)} "
                                                      f"that could not be placed: {'; '.join(skipped)}"[:450])
            print(f"  {len(skipped)} dropped, {resolved} schools kept")
        sheet.set_blog(blogs_ws, b["_row"], status="cms_done")
        sheet.archive_block(sh, kw)


def cmd_write(sh, args):
    blogs_ws = sh.worksheet(sheet.BLOGS)
    done = sheet.records(sh.worksheet(sheet.CMS))
    for b in rows_in(sheet.records(blogs_ws), "cms_done", args):
        kw = b["Keyword"].strip()
        # page_name is the name the directory pages used, which is how pick.json keys its
        # rating counts. It is often spelled differently from the CMS name.
        picked = [{"name": r["CMS name"], "id": r["CMS ID"], "slug": r["CMS slug"],
                   "area": r.get("Area", ""), "page_name": r.get("School", "")}
                  for r in cms_rows(done, kw)]
        print(f"write: {kw} ({len(picked)} schools). This takes a while...")
        try:
            path, problems = write_stage.write_blog(kw, b["City"], b["Area"], b["Slug"] or blog_slug(kw, b["City"]), picked)
        except ClaudeError as err:
            sheet.set_blog(blogs_ws, b["_row"], error=f"write: {err}")
            print(f"  error: {err}")
            continue
        sheet.set_blog(blogs_ws, b["_row"], status="written")
        print(f"  saved {path}")
        for p in problems:
            print(f"  asset: {p}")


def cmd_qc(sh, args):
    blogs_ws = sh.worksheet(sheet.BLOGS)
    done = sheet.records(sh.worksheet(sheet.CMS))
    blogs = sheet.records(blogs_ws)
    for b in rows_in(blogs, "written", args) + rows_in(blogs, "qc_fail", args):
        kw = b["Keyword"].strip()
        folder = blog_folder(b)
        blog = os.path.join(folder, "blog.md")
        if not os.path.exists(blog):
            sheet.set_blog(blogs_ws, b["_row"], error=f"qc: {blog} not found")
            continue
        with open(blog, encoding="utf-8") as fh:
            md = fh.read()
        rows = cms_rows(done, kw)
        ids = [r["CMS ID"] for r in rows if r["CMS ID"].strip()]
        # The CMS slug per school, for the [read_more_blogs] links. They are built from it and
        # used to be rebuilt from the school's name instead, which drops the locality the slug
        # ends in and points every link at a page that does not exist.
        # A list per name, because a chain can put several campuses in one blog under one CMS
        # name: Bhubaneswar had three "DAV Public School" rows, and keeping one slug per name
        # failed the two that lost over links that were right.
        slugs = {}
        for r in rows:
            if r["CMS slug"].strip():
                slugs.setdefault(r["CMS name"], []).append(r["CMS slug"])
        meta_path = os.path.join(folder, "meta.json")
        meta = json.load(open(meta_path, encoding="utf-8")) if os.path.exists(meta_path) else {}
        # notes.md carries the researcher's record of what it tried. A fee or a review
        # nobody publishes is declared there, and qc excuses that one section rather than
        # leaving the blog permanently unpassable.
        notes_path = os.path.join(folder, "notes.md")
        notes = open(notes_path, encoding="utf-8").read() if os.path.exists(notes_path) else ""
        passed, lines = qc_stage.check_blog(md, kw, expected_ids=ids, folder=folder, meta=meta,
                                            notes=notes, expected_slugs=slugs)
        with open(os.path.join(folder, "qc.txt"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        fails = [l for l in lines if l.startswith("FAIL")]
        sheet.set_blog(blogs_ws, b["_row"], status="qc_pass" if passed else "qc_fail",
                       error="; ".join(f[5:] for f in fails)[:450])
        print(f"qc: {kw}: {'PASS' if passed else f'{len(fails)} issues'}")


def cmd_draft(sh, args):
    """Stage 5: create an UNPUBLISHED draft in their CMS for a QC-passed blog.

    --row is required on purpose. This is the first command that writes to their live site,
    and a bare `draft` that swept every qc_pass row is not a mistake worth making cheap.

    Status is left at qc_pass: their API has no publish endpoint, so a draft is not a
    published post, and the sheet's Status validation is strict about its eight values.
    What records the draft is the Live link column, which holds the edit_url.
    """
    from clients.blog_base import BlogError, get_blog
    from stages import draft as draft_stage

    blogs_ws = sh.worksheet(sheet.BLOGS)
    done = sheet.records(sh.worksheet(sheet.CMS))
    blog_cms = get_blog()
    for b in rows_in(sheet.records(blogs_ws), "qc_pass", args):
        kw, folder = b["Keyword"].strip(), blog_folder(b)
        meta_path = os.path.join(folder, "meta.json")
        if not os.path.exists(meta_path):
            sheet.set_blog(blogs_ws, b["_row"], error=f"draft: no meta.json in {folder}")
            print(f"draft: {kw}: no meta.json, skipped")
            continue
        with open(meta_path, encoding="utf-8") as fh:
            meta = json.load(fh)
        schools = len([r for r in cms_rows(done, kw) if r["CMS ID"].strip()])
        print(f"draft: {kw}")
        try:
            out = draft_stage.create(blog_cms, folder, meta, b["City"].strip(),
                                     b["Area"].strip(), expect_schools=schools)
        except BlogError as err:
            sheet.set_blog(blogs_ws, b["_row"], error=f"draft: {err}"[:450])
            print(f"  failed: {err}")
            continue
        sheet.set_blog(blogs_ws, b["_row"], error="", **{"Live link": out["edit_url"]})
        # None, not 0, when their reply left linked_schools out. The two must not print the
        # same: one is a broken shortcode, the other is them not telling us.
        linked = out["linked_schools"]
        print(f"  draft {out['id']} ({out['status']}), "
              + (f"{linked} of {schools} schools linked" if linked is not None
                 else f"schools linked not reported (the blog has {schools})"))
        for warning in out["warnings"]:
            print(f"  check: {warning}")
        print(f"  open: {out['edit_url']}")


def cmd_docx(sh, args):
    """Rebuild blog.docx from blog.md, e.g. after hand edits. Any blog that has been written."""
    from stages import docx_export
    for b in sheet.records(sh.worksheet(sheet.BLOGS)):
        if args.row and b["Keyword"].strip().lower() not in wanted(args):
            continue
        folder = blog_folder(b)
        if os.path.exists(os.path.join(folder, "blog.md")):
            try:
                print(f"docx: {docx_export.export(folder)}")
            except PermissionError as err:
                print(f"docx: {err}")


def cmd_show(sh, args):
    """Numbered school list per picked blog, for choosing in chat."""
    picks = sheet.read_picks(sh.worksheet(sheet.SCHOOLS))
    for b in rows_in(sheet.records(sh.worksheet(sheet.BLOGS)), "picked", args):
        block = picks.get(b["Keyword"].strip().lower())
        if not block:
            print(f"{b['Keyword']}: no school list in the Schools tab, rerun pick")
            continue
        print(f"\n{b['Keyword']} ({len(block['schools'])} found)")
        for i, s in enumerate(block["schools"], 1):
            vol = f"  vol {s['volume']}" if s["volume"] else ""
            tick = "  [ticked]" if s["approved"] else ""
            # A blank area is not fatal here: the cms stage looks it up. It is shown because
            # typing it into the sheet's Area column is faster and surer than the lookup.
            where = f"  {s['area']}" if s.get("area") else "  [no area]"
            print(f"  {i:>2}. {s['name']}  count {s['count']}{vol}{where}{tick}")


def _one_block(sh, args, cmd):
    if len(args.row) != 1:
        sys.exit(f"{cmd} takes exactly one --row")
    rows = rows_in(sheet.records(sh.worksheet(sheet.BLOGS)), "picked", args)
    if not rows:
        sys.exit(f"No picked blog called '{args.row[0]}'")
    block = sheet.read_picks(sh.worksheet(sheet.SCHOOLS)).get(rows[0]["Keyword"].strip().lower())
    if not block:
        sys.exit(f"{rows[0]['Keyword']}: no school list in the Schools tab")
    return rows[0], block


def cmd_setvol(sh, args):
    """Write volumes by list number, e.g. from a screenshot or typed in chat."""
    b, block = _one_block(sh, args, "setvol")
    try:
        vols = parse_vols(args.vols, len(block["schools"]))
    except ValueError as err:
        sys.exit(f"Can't use '{args.vols}': {err}")
    sheet.set_volumes(sh.worksheet(sheet.SCHOOLS), [(block["schools"][n - 1]["row"], v) for n, v in vols.items()])
    for n, v in sorted(vols.items()):
        print(f"  {n:>2}. {block['schools'][n - 1]['name']}: {v}")
    left = len(block["schools"]) - len({n for n in range(1, len(block["schools"]) + 1)
                                        if block["schools"][n - 1]["volume"] or n in vols})
    print(f"{b['Keyword']}: {len(vols)} volumes set, {left} still blank")


def cmd_suggest(sh, args):
    """Schools chosen by the volume rule, per picked blog, with the selection to pass to approve."""
    picks = sheet.read_picks(sh.worksheet(sheet.SCHOOLS))
    for b in rows_in(sheet.records(sh.worksheet(sheet.BLOGS)), "picked", args):
        block = picks.get(b["Keyword"].strip().lower())
        if not block:
            continue
        try:
            nums, topup = suggest_schools(block["schools"])
        except ValueError as err:
            print(f"\n{b['Keyword']}: {err}")
            continue
        print(f"\n{b['Keyword']}: {len(nums)} chosen")
        blank = []
        for n in nums:
            s = block["schools"][n - 1]
            where = s.get("area") or ""
            if not where:
                blank.append(n)
            print(f"  {n:>2}. {s['name']}  vol {s['volume']}"
                  f"  {where or '[no area]'}{'  (top-up)' if n in topup else ''}")
        print(f"  selection: {','.join(map(str, sorted(nums)))}")
        if blank:
            print(f"  {len(blank)} with no area ({', '.join(map(str, blank))}). The cms stage will "
                  f"look them up, or fill the Area column in the Schools tab to be sure.")


def cmd_approve(sh, args):
    """Tick the chosen schools for one picked blog and set it to approved."""
    if len(args.row) != 1:
        sys.exit("approve takes exactly one --row")
    blogs_ws, schools_ws = sh.worksheet(sheet.BLOGS), sh.worksheet(sheet.SCHOOLS)
    rows = rows_in(sheet.records(blogs_ws), "picked", args)
    if not rows:
        sys.exit(f"No picked blog called '{args.row[0]}'")
    b = rows[0]
    block = sheet.read_picks(schools_ws).get(b["Keyword"].strip().lower())
    if not block:
        sys.exit(f"{b['Keyword']}: no school list in the Schools tab")
    try:
        nums = parse_selection(args.schools, len(block["schools"]))
    except ValueError as err:
        sys.exit(f"Can't use '{args.schools}': {err}")
    if not 8 <= len(nums) <= 12:
        sys.exit(f"{len(nums)} schools chosen, need 8-12")
    chosen = [block["schools"][n - 1] for n in nums]
    sheet.set_ticks(schools_ws, block, {s["row"] for s in chosen})
    sheet.set_blog(blogs_ws, b["_row"], status="approved")
    print(f"Approved {b['Keyword']} with {len(chosen)} schools: " + ", ".join(s["name"] for s in chosen))


def cmd_status(sh, args):
    blogs = mine(sheet.records(sh.worksheet(sheet.BLOGS)))
    if config.WRITER:
        print(f"Only {config.WRITER}'s keywords (WRITER in .env)")
    counts = Counter(b["Status"].strip() or "(blank)" for b in blogs)
    for s in sheet.STATUSES:
        print(f"  {s:<10} {counts.get(s, 0)}")
    errors = [b for b in blogs if b["Error"].strip()]
    print(f"\n{len(blogs)} keywords, {len(errors)} with errors")
    for b in errors[:10]:
        print(f"  {b['Keyword']}: {b['Error'][:120]}")
    nxt = [b["Keyword"] for b in blogs if b["Status"].strip() == "new"][:10]
    if nxt:
        print("\nNext new, in sheet order:\n" + "\n".join(f"  {k}" for k in nxt))


def cmd_topup(sh, args):
    """The browser half's worklist, and the merge back. See BROWSER_TOPUP.md.

    Reviews, scanned fee tables and building photos are the three fields a headless
    researcher cannot reach, because claude_cli runs with --strict-mcp-config and so has no
    browser. This command is both ends of that gap and none of the middle: it says which
    schools still need a browser, and it merges what a browser session found. The browser
    work itself happens in a desktop session, via the school-topper agent.
    """
    if args.apply:
        try:
            patches = topup_stage.read_patches(args.apply)
        except ValueError as err:
            print(f"topup: {err}")
            return
        done, failed = 0, 0
        for cms_id, fields in patches.items():
            changed, problem = topup_stage.apply_patch(topup_stage.sheet_path(cms_id), fields)
            if problem:
                print(f"  skipped {problem}")
                failed += 1
            elif changed:
                print(f"  {cms_id}: {', '.join(changed)}")
                done += 1
            else:
                # a batched topper returns an entry per school, empty when it found nothing
                print(f"  {cms_id}: nothing found")
        print(f"topup --apply: {done} sheets updated, {failed} refused")
        return

    blogs = sheet.records(sh.worksheet(sheet.BLOGS))
    done_rows = sheet.records(sh.worksheet(sheet.CMS))
    rows = [b for b in mine(blogs)
            if not args.row or b["Keyword"].strip().lower() in wanted(args)]
    photo_budget, over_budget = topup_stage.image_cap(), 0
    for b in rows[:args.limit] if args.limit else rows:
        kw, city = b["Keyword"].strip(), b["City"].strip()
        schools = [{"id": r["CMS ID"], "name": r["CMS name"], "city": city,
                    "area": r.get("Area", "")} for r in cms_rows(done_rows, kw)]
        if not schools:
            continue
        work, no_sheet = topup_stage.worklist(schools)
        # The photo hunt has a token ceiling (IMAGE_BUDGET in stages/topup.py). Past it the
        # image group is dropped from the worklist and the run says so at the end, rather
        # than quietly spending more.
        work, photo_budget, dropped = topup_stage.spend_image_budget(work, photo_budget)
        over_budget += dropped
        folder = blog_folder(b)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "topup.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(work, fh, indent=2, ensure_ascii=False)
        tally = Counter(g for w in work for g in w["needs"])
        print(f"topup: {kw}: {len(work)} of {len(schools)} schools need a browser"
              f"{' (' + ', '.join(f'{k} {v}' for k, v in sorted(tally.items())) + ')' if tally else ''}")
        for w in work:
            print(f"  {w['id']:>6} {w['name']}: {', '.join(w['needs'])}")
        if no_sheet:
            print(f"  no stored sheet yet (research, not top-up): {', '.join(no_sheet)}")
        print(f"  worklist: {path}")
    if over_budget:
        print(f"topup: photo budget spent after {topup_stage.image_cap()} schools "
              f"(~{topup_stage.IMAGE_BUDGET:,} tokens). {over_budget} more need a photo and "
              f"were left out -- run topup again for those, or add them by hand.")


def main():
    p = argparse.ArgumentParser(description="Yellow Slate blog pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup")
    a = sub.add_parser("add")
    a.add_argument("keyword", nargs="+")
    a.add_argument("--city", required=True)
    a.add_argument("--area", default="")
    for name in ("pick", "cms", "write", "qc"):
        s = sub.add_parser(name)
        s.add_argument("--limit", type=int, default=0)
        s.add_argument("--row", action="append", default=[], help="only this keyword (repeatable)")
    d = sub.add_parser("docx", help="rebuild blog.docx from blog.md")
    d.add_argument("--row", action="append", default=[], help="only this keyword (repeatable)")
    sh_ = sub.add_parser("show", help="numbered school list for picked blogs")
    sh_.add_argument("--row", action="append", default=[], help="only this keyword (repeatable)")
    sv = sub.add_parser("setvol", help="write volumes by list number")
    sv.add_argument("--row", action="append", default=[], required=True)
    sv.add_argument("--vols", required=True, help='e.g. "1:320, 2:90, 5:1,500"')
    sg = sub.add_parser("suggest", help="schools chosen by the volume rule")
    sg.add_argument("--row", action="append", default=[], help="only this keyword (repeatable)")
    ap = sub.add_parser("approve", help="tick chosen schools and set the blog to approved")
    ap.add_argument("--row", action="append", default=[], required=True)
    ap.add_argument("--schools", required=True, help='e.g. "1-10" or "1-12 drop 4,7"')
    dr = sub.add_parser("draft", help="create an unpublished draft in their CMS (qc_pass rows)")
    dr.add_argument("--row", action="append", default=[], required=True,
                    help="only this keyword (repeatable). Required: this writes to their site.")
    tu = sub.add_parser("topup", help="which schools still need a browser, and merge what it found")
    tu.add_argument("--row", action="append", default=[], help="only this keyword (repeatable)")
    tu.add_argument("--limit", type=int, default=0)
    tu.add_argument("--apply", default="", metavar="FILE",
                    help="merge a browser session's patches into the stored sheets")
    sub.add_parser("names", help="Semrush paste list of school names missing a volume")
    sub.add_parser("volumes", help="fill Vol from Semrush exports in data/semrush/")
    sub.add_parser("status")
    args = p.parse_args()

    sh = sheet.open_sheet()
    {"setup": cmd_setup, "add": cmd_add, "pick": cmd_pick, "cms": cmd_cms,
     "write": cmd_write, "qc": cmd_qc, "status": cmd_status,
     "names": cmd_names, "volumes": cmd_volumes, "docx": cmd_docx, "draft": cmd_draft,
     "show": cmd_show, "approve": cmd_approve, "setvol": cmd_setvol, "suggest": cmd_suggest,
     "topup": cmd_topup}[args.cmd](sh, args)


if __name__ == "__main__":
    main()
