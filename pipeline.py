#!/usr/bin/env python
"""
Yellow Slate 600-blog pipeline. The Google Sheet is the control center.

Flow per keyword (Blogs tab Status column):
  new -> pick -> picked -> [Harshit ticks schools, sets approved] -> cms -> cms_done
      -> write -> written -> qc -> qc_pass | qc_fail -> [Harshit reviews + publishes] -> published

Commands
--------
  python pipeline.py setup                       build/refresh the sheet tabs (safe to re-run)
  python pipeline.py add "<keyword>" --city C [--area A]   add one keyword row
  python pipeline.py pick   [--limit N] [--row KEYWORD]
  python pipeline.py cms    [--limit N] [--row KEYWORD]
  python pipeline.py write  [--limit N] [--row KEYWORD]
  python pipeline.py qc     [--limit N] [--row KEYWORD]
  python pipeline.py status

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
from stages.names import slugify

S = sheet.SCHOOL_HEADERS


def area_from_keyword(keyword):
    m = re.search(r"\bin\s+(.+)$", keyword, re.I)
    return m.group(1).strip().title() if m else ""


def rows_in(blogs, status, args):
    rows = [b for b in blogs if b["Status"].strip() == status]
    if args.row:
        rows = [b for b in rows if b["Keyword"].strip().lower() == args.row.lower()]
    return rows[: args.limit] if args.limit else rows


def blog_schools(schools, keyword, ticked_only=True):
    out = [s for s in schools if s["Keyword"].strip().lower() == keyword.strip().lower()]
    return [s for s in out if sheet.is_ticked(s["Approve"])] if ticked_only else out


# --------------------------------------------------------------------------- #


def cmd_setup(sh, args):
    sheet.setup(sh)
    print("Sheet ready: Blogs, Schools, Weekly review.")


def cmd_add(sh, args):
    ws = sh.worksheet(sheet.BLOGS)
    if any(b["Keyword"].strip().lower() == args.keyword.lower() for b in sheet.records(ws)):
        sys.exit(f"Already in the sheet: {args.keyword}")
    area = args.area or area_from_keyword(args.keyword)
    ws.append_row([args.keyword, args.city, area, slugify(args.keyword), "new", "", "", "", ""],
                  value_input_option="USER_ENTERED")
    print(f"Added: {args.keyword} | {args.city} | {area}")


def cmd_pick(sh, args):
    blogs_ws, schools_ws = sh.worksheet(sheet.BLOGS), sh.worksheet(sheet.SCHOOLS)
    for b in rows_in(sheet.records(blogs_ws), "new", args):
        kw = b["Keyword"].strip()
        print(f"pick: {kw}")
        try:
            shortlist, n_pages = pick_stage.candidates(kw, b["City"])
        except (TavilyError, ClaudeError) as err:
            sheet.set_blog(blogs_ws, b["_row"], error=f"pick: {err}")
            print(f"  error: {err}")
            continue
        if not shortlist:
            sheet.set_blog(blogs_ws, b["_row"], error="pick: no competitor school lists found")
            print("  no schools found")
            continue
        rows = [[kw, s["name"], s["count"], " ".join(s["sources"]), False, "", "", "", ""] for s in shortlist]
        schools_ws.append_rows(rows, value_input_option="USER_ENTERED")
        sheet.set_blog(blogs_ws, b["_row"], status="picked")
        print(f"  {len(shortlist)} schools from {n_pages} pages. Top: "
              + ", ".join(f"{s['name']} ({s['count']})" for s in shortlist[:5]))


def cmd_cms(sh, args):
    blogs_ws, schools_ws = sh.worksheet(sheet.BLOGS), sh.worksheet(sheet.SCHOOLS)
    cms = get_cms()
    schools = sheet.records(schools_ws)
    for b in rows_in(sheet.records(blogs_ws), "approved", args):
        kw, city, area = b["Keyword"].strip(), b["City"].strip(), b["Area"].strip()
        picked = blog_schools(schools, kw)
        if not city or not area:
            sheet.set_blog(blogs_ws, b["_row"], error="cms: City and Area must be filled")
            continue
        if not 8 <= len(picked) <= 12:
            sheet.set_blog(blogs_ws, b["_row"], error=f"cms: {len(picked)} schools ticked, need 8-12")
            print(f"cms: {kw}: {len(picked)} ticked, skipped")
            continue
        print(f"cms: {kw}")
        try:
            for s in picked:
                if s["CMS ID"].strip():
                    continue  # done on an earlier run
                res = cms_stage.ensure_school(cms, s["School"], city, area)
                sheet.update(schools_ws, S, s["_row"], {
                    "CMS ID": res["id"], "CMS slug": res["slug"], "Created by us": "y" if res["created"] else "n"})
                print(f"  {'created' if res['created'] else 'exists '} {res['id']} {res['name']}")
        except CMSError as err:
            sheet.set_blog(blogs_ws, b["_row"], error=f"cms: {err}")
            print(f"  error: {err}")
            continue
        sheet.set_blog(blogs_ws, b["_row"], status="cms_done")


def cmd_write(sh, args):
    blogs_ws, schools_ws = sh.worksheet(sheet.BLOGS), sh.worksheet(sheet.SCHOOLS)
    schools = sheet.records(schools_ws)
    for b in rows_in(sheet.records(blogs_ws), "cms_done", args):
        kw = b["Keyword"].strip()
        picked = [{"name": s["School"], "id": s["CMS ID"], "slug": s["CMS slug"]} for s in blog_schools(schools, kw)]
        print(f"write: {kw} ({len(picked)} schools). This takes a while...")
        try:
            path = write_stage.write_blog(kw, b["City"], b["Area"], b["Slug"] or slugify(kw), picked)
        except ClaudeError as err:
            sheet.set_blog(blogs_ws, b["_row"], error=f"write: {err}")
            print(f"  error: {err}")
            continue
        sheet.set_blog(blogs_ws, b["_row"], status="written")
        print(f"  saved {path}")


def cmd_qc(sh, args):
    blogs_ws, schools_ws = sh.worksheet(sheet.BLOGS), sh.worksheet(sheet.SCHOOLS)
    schools = sheet.records(schools_ws)
    for b in rows_in(sheet.records(blogs_ws), "written", args) + rows_in(sheet.records(blogs_ws), "qc_fail", args):
        kw = b["Keyword"].strip()
        folder = os.path.join(config.OUTPUT_DIR, b["Slug"] or slugify(kw))
        blog = os.path.join(folder, "blog.md")
        if not os.path.exists(blog):
            sheet.set_blog(blogs_ws, b["_row"], error=f"qc: {blog} not found")
            continue
        with open(blog, encoding="utf-8") as fh:
            md = fh.read()
        ids = [s["CMS ID"] for s in blog_schools(schools, kw) if s["CMS ID"].strip()]
        meta_path = os.path.join(folder, "meta.json")
        meta = json.load(open(meta_path, encoding="utf-8")) if os.path.exists(meta_path) else {}
        passed, lines = qc_stage.check_blog(md, kw, expected_ids=ids, folder=folder, meta=meta)
        with open(os.path.join(folder, "qc.txt"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        fails = [l for l in lines if l.startswith("FAIL")]
        sheet.set_blog(blogs_ws, b["_row"], status="qc_pass" if passed else "qc_fail",
                       error="; ".join(f[5:] for f in fails)[:450])
        print(f"qc: {kw}: {'PASS' if passed else f'{len(fails)} issues'}")


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
    a.add_argument("keyword")
    a.add_argument("--city", required=True)
    a.add_argument("--area", default="")
    for name in ("pick", "cms", "write", "qc"):
        s = sub.add_parser(name)
        s.add_argument("--limit", type=int, default=0)
        s.add_argument("--row", default="", help="only this keyword")
    sub.add_parser("status")
    args = p.parse_args()

    sh = sheet.open_sheet()
    {"setup": cmd_setup, "add": cmd_add, "pick": cmd_pick, "cms": cmd_cms,
     "write": cmd_write, "qc": cmd_qc, "status": cmd_status}[args.cmd](sh, args)


if __name__ == "__main__":
    main()
