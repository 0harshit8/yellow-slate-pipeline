#!/usr/bin/env python
"""
Yellow Slate 600-blog pipeline. The Google Sheet is the control center.

Flow per keyword (Blogs tab Status column):
  new -> pick -> picked -> [Harshit ticks schools, sets approved] -> cms -> cms_done
      -> write -> written -> qc -> qc_pass | qc_fail -> [Harshit reviews + publishes] -> published

Commands
--------
  python pipeline.py setup                       build/refresh the sheet tabs (safe to re-run)
  python pipeline.py add "<kw>" ["<kw>" ...] --city C [--area A]   add keyword rows (duplicates skipped)
  python pipeline.py pick   [--limit N] [--row KEYWORD]
  python pipeline.py cms    [--limit N] [--row KEYWORD]
  python pipeline.py write  [--limit N] [--row KEYWORD]
  python pipeline.py qc     [--limit N] [--row KEYWORD]
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
from stages import write as write_stage
from stages.names import blog_slug, semrush_term
from stages.selection import new_keywords, parse_selection, parse_vols, suggest_schools
from stages.semrush import semrush_volumes

SEMRUSH_DIR = os.path.join(config.DATA_DIR, "semrush")

def area_from_keyword(keyword):
    m = re.search(r"\bin\s+(.+)$", keyword, re.I)
    return m.group(1).strip().title() if m else ""


def wanted(args):
    return {r.strip().lower() for r in args.row}


def rows_in(blogs, status, args):
    rows = [b for b in blogs if b["Status"].strip() == status]
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
        rows.append([kw, args.city, area, blog_slug(kw, args.city), "new", "", "", "", ""])
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
        if not 8 <= len(picked) <= 12:
            sheet.set_blog(blogs_ws, b["_row"], error=f"cms: {len(picked)} schools ticked, need 8-12")
            print(f"cms: {kw}: {len(picked)} ticked, skipped")
            continue
        print(f"cms: {kw}")
        have = {r["School"].strip().lower() for r in cms_rows(done, kw) if r["CMS ID"].strip()}
        new_rows, failed = [], None
        for s in picked:
            if s["name"].lower() in have:
                continue  # done on an earlier run
            try:
                res = cms_stage.ensure_school(cms, s["name"], city, area)
            except CMSError as err:
                failed = err
                break
            new_rows.append([kw, s["name"], res["name"], res["id"], res["slug"], "y" if res["created"] else "n"])
            print(f"  {'created' if res['created'] else 'exists '} {res['id']} {res['name']}")
        if new_rows:
            sheet.append(cms_ws, new_rows)  # keep what succeeded, even if a later school failed
        if failed:
            sheet.set_blog(blogs_ws, b["_row"], error=f"cms: {failed}")
            print(f"  error: {failed}")
            continue
        sheet.set_blog(blogs_ws, b["_row"], status="cms_done")
        sheet.archive_block(sh, kw)


def cmd_write(sh, args):
    blogs_ws = sh.worksheet(sheet.BLOGS)
    done = sheet.records(sh.worksheet(sheet.CMS))
    for b in rows_in(sheet.records(blogs_ws), "cms_done", args):
        kw = b["Keyword"].strip()
        picked = [{"name": r["CMS name"], "id": r["CMS ID"], "slug": r["CMS slug"]} for r in cms_rows(done, kw)]
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
        ids = [r["CMS ID"] for r in cms_rows(done, kw) if r["CMS ID"].strip()]
        meta_path = os.path.join(folder, "meta.json")
        meta = json.load(open(meta_path, encoding="utf-8")) if os.path.exists(meta_path) else {}
        passed, lines = qc_stage.check_blog(md, kw, expected_ids=ids, folder=folder, meta=meta)
        with open(os.path.join(folder, "qc.txt"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        fails = [l for l in lines if l.startswith("FAIL")]
        sheet.set_blog(blogs_ws, b["_row"], status="qc_pass" if passed else "qc_fail",
                       error="; ".join(f[5:] for f in fails)[:450])
        print(f"qc: {kw}: {'PASS' if passed else f'{len(fails)} issues'}")


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
            print(f"  {i:>2}. {s['name']}  count {s['count']}{vol}{tick}")


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
        for n in nums:
            s = block["schools"][n - 1]
            print(f"  {n:>2}. {s['name']}  vol {s['volume']}{'  (top-up)' if n in topup else ''}")
        print(f"  selection: {','.join(map(str, sorted(nums)))}")


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
    blogs = sheet.records(sh.worksheet(sheet.BLOGS))
    counts = Counter(b["Status"].strip() or "(blank)" for b in blogs)
    for s in sheet.STATUSES:
        print(f"  {s:<10} {counts.get(s, 0)}")
    errors = [b for b in blogs if b["Error"].strip()]
    print(f"\n{len(blogs)} keywords, {len(errors)} with errors")
    for b in errors[:10]:
        print(f"  {b['Keyword']}: {b['Error'][:120]}")


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
    sub.add_parser("names", help="Semrush paste list of school names missing a volume")
    sub.add_parser("volumes", help="fill Vol from Semrush exports in data/semrush/")
    sub.add_parser("status")
    args = p.parse_args()

    sh = sheet.open_sheet()
    {"setup": cmd_setup, "add": cmd_add, "pick": cmd_pick, "cms": cmd_cms,
     "write": cmd_write, "qc": cmd_qc, "status": cmd_status,
     "names": cmd_names, "volumes": cmd_volumes, "docx": cmd_docx,
     "show": cmd_show, "approve": cmd_approve, "setvol": cmd_setvol, "suggest": cmd_suggest}[args.cmd](sh, args)


if __name__ == "__main__":
    main()
