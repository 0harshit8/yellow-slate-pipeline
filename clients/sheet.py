"""Google Sheet control center. Same service-account pattern as the AIOS scripts/sheets.py.

The sheet is created by hand and shared (Editor) with the service account email,
because a service account can't own Drive files. Then `python pipeline.py setup`.

Tabs
  Blogs          one row per keyword, Status drives the pipeline
  Schools        Harshit's approval queue: only blogs waiting for approval, stacked
                 top to bottom (yellow keyword bar, then School | Count | Vol | ✓)
  Schools archive  flat record of every processed blog's candidates, moved here after cms
  CMS            pipeline's record: CMS ID + slug per approved school
  Weekly review  formulas only, for the weekly call
"""

import os
import sys
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials

import config

SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

BLOGS = "Blogs"
SCHOOLS = "Schools"
CMS = "CMS"
WEEKLY = "Weekly review"
ARCHIVE = "Schools archive"

BLOG_HEADERS = ["Keyword", "City", "Area", "Slug", "Status", "Error", "Live link", "Minutes", "Updated"]
CMS_HEADERS = ["Keyword", "School", "CMS name", "CMS ID", "CMS slug", "Created by us"]
ARCHIVE_HEADERS = ["Keyword", "School", "Count", "Vol", "Approved"]
STATUSES = ["new", "picked", "approved", "cms_done", "written", "qc_pass", "qc_fail", "published"]

# Schools queue columns. E (blog) and F (row kind) are hidden bookkeeping.
QUEUE_HEADERS = ["School", "Count", "Vol", "✓", "Blog", "Kind"]
MAX_SCHOOLS = 15


def open_sheet():
    if not os.path.exists(config.GCP_KEY):
        sys.exit(f"Service account key not found at {config.GCP_KEY}. Set GCP_KEY in .env.")
    if not config.SHEET_ID:
        sys.exit("SHEET_ID is empty. Create the sheet, share it with the service account, set SHEET_ID in .env.")
    creds = Credentials.from_service_account_file(config.GCP_KEY, scopes=SCOPES)
    return gspread.authorize(creds).open_by_key(config.SHEET_ID)


def col_letter(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def setup(sh):
    """Builds the tabs. Safe to re-run: only creates what's missing and rewrites headers."""
    existing = {w.title: w for w in sh.worksheets()}
    if BLOGS not in existing and "Sheet1" in existing:
        existing["Sheet1"].update_title(BLOGS)
        existing[BLOGS] = existing.pop("Sheet1")
    for name, rows, cols in ((BLOGS, 1000, len(BLOG_HEADERS)), (SCHOOLS, 500, len(QUEUE_HEADERS)),
                             (ARCHIVE, 10000, len(ARCHIVE_HEADERS)), (CMS, 10000, len(CMS_HEADERS)),
                             (WEEKLY, 30, 4)):
        if name not in existing:
            existing[name] = sh.add_worksheet(title=name, rows=rows, cols=cols)

    for name, headers in ((BLOGS, BLOG_HEADERS), (CMS, CMS_HEADERS), (ARCHIVE, ARCHIVE_HEADERS)):
        ws = existing[name]
        ws.update(values=[headers], range_name="A1")
        ws.freeze(rows=1)
        ws.format(f"A1:{col_letter(len(headers))}1", {"textFormat": {"bold": True}})
    render_queue(existing[SCHOOLS], read_queue(existing[SCHOOLS]))

    status_col = BLOG_HEADERS.index("Status")
    sh.batch_update({"requests": [_validation(existing[BLOGS].id, 1, None, status_col, {
        "type": "ONE_OF_LIST", "values": [{"userEnteredValue": s} for s in STATUSES]})]})

    # Weekly review: formulas only, so it's always current for the call.
    week_start = "TODAY()-WEEKDAY(TODAY(),2)+1"
    grid = [
        ["Weekly review", "", "", ""],
        ["", "This week", "Total", "Target"],
        ["Blogs published",
         f'=COUNTIFS(Blogs!E:E,"published",Blogs!I:I,">="&{week_start})',
         '=COUNTIF(Blogs!E:E,"published")', 600],
        ["Schools added to CMS", "", '=COUNTIF(CMS!F:F,"y")', ""],
        ["Avg minutes per blog", "", '=IFERROR(AVERAGE(Blogs!H2:H),"")', 15],
        ["", "", "", ""],
        ["Status", "Blogs", "", ""],
    ] + [[s, f'=COUNTIF(Blogs!E:E,"{s}")', "", ""] for s in STATUSES]
    existing[WEEKLY].update(values=grid, range_name="A1", value_input_option="USER_ENTERED")
    existing[WEEKLY].format("A1:D2", {"textFormat": {"bold": True}})


def _validation(sheet_id, start_row, end_row, col, condition):
    """start_row is 0-based (1 = skip header). end_row None = to the bottom."""
    rng = {"sheetId": sheet_id, "startRowIndex": start_row, "startColumnIndex": col, "endColumnIndex": col + 1}
    if end_row is not None:
        rng["endRowIndex"] = end_row
    return {"setDataValidation": {"range": rng, "rule": {"condition": condition, "strict": True, "showCustomUi": True}}}


# --------------------------------------------------------------------------- #
# Row tabs (Blogs, CMS)


def records(ws):
    """Rows with a value in column A, as dicts keyed by header, each with "_row" (1-based)."""
    values = ws.get_all_values()
    if not values:
        return []
    headers = values[0]
    out = []
    for i, row in enumerate(values[1:], start=2):
        if not row or not row[0].strip():
            continue
        row = row + [""] * (len(headers) - len(row))
        rec = dict(zip(headers, row))
        rec["_row"] = i
        out.append(rec)
    return out


def append(ws, rows):
    """Write rows starting at the first row with an empty column A."""
    col_a = ws.col_values(1)
    start = len(col_a) + 1
    for i, v in enumerate(col_a[1:], start=2):
        if not v.strip():
            start = i
            break
    end = start + len(rows) - 1
    if end > ws.row_count:
        ws.add_rows(end - ws.row_count)
    ws.update(values=rows, range_name=f"A{start}:{col_letter(len(rows[0]))}{end}",
              value_input_option="USER_ENTERED")


def update(ws, headers, row, fields):
    """Write {header: value} into one row."""
    data = [{"range": f"{col_letter(headers.index(k) + 1)}{row}", "values": [[v]]} for k, v in fields.items()]
    ws.batch_update(data, value_input_option="USER_ENTERED")


def set_blog(ws, row, status=None, error="", **extra):
    fields = {"Error": error, "Updated": datetime.now().strftime("%Y-%m-%d %H:%M")}
    if status:
        fields["Status"] = status
    fields.update(extra)
    update(ws, BLOG_HEADERS, row, fields)


# --------------------------------------------------------------------------- #
# Schools queue: blogs waiting for approval, stacked top to bottom

YELLOW = {"red": 1.0, "green": 0.93, "blue": 0.6}


def read_queue(ws):
    """[{"keyword", "schools": [{"name", "count", "volume", "approved", "row"}]}] in sheet order."""
    values = ws.get_all_values()
    blocks, by_kw = [], {}
    for i, row in enumerate(values[1:], start=2):
        row = row + [""] * (len(QUEUE_HEADERS) - len(row))
        name, count, vol, tick, kw, kind = (c.strip() for c in row[:6])
        if not kw:
            continue
        if kw.lower() not in by_kw:
            by_kw[kw.lower()] = {"keyword": kw, "schools": []}
            blocks.append(by_kw[kw.lower()])
        if kind == "school" and name:
            by_kw[kw.lower()]["schools"].append({
                "name": name, "count": count, "volume": vol,
                "approved": tick.upper() == "TRUE", "row": i})
    return blocks


def read_picks(ws):
    """{keyword_lower: block} view of read_queue."""
    return {b["keyword"].lower(): b for b in read_queue(ws)}


def render_queue(ws, blocks):
    """Rewrite the whole queue tab from blocks, keeping ticks and volumes they carry.

    Don't tick boxes while a pipeline command is running: a rewrite in the middle
    of your edit would drop that tick.
    """
    rows = [QUEUE_HEADERS]
    headers, schools = [], []  # 0-based row indexes
    for b in blocks:
        headers.append(len(rows))
        kw = b["keyword"].replace('"', '""')
        ticked = f'=COUNTIFS(E:E,"{kw}",F:F,"school",D:D,TRUE)&" of 8-12 ticked"'
        rows.append([b["keyword"], ticked, "", "", b["keyword"], "blog"])
        start = len(rows)
        for s in b["schools"]:
            rows.append([s["name"], s["count"], s["volume"], bool(s["approved"]), b["keyword"], "school"])
        schools.append((start, len(rows)))
        rows.append(["", "", "", "", "", ""])

    need = max(len(rows) + 50, 200)
    sid = ws.id
    requests = [
        {"updateCells": {"range": {"sheetId": sid}, "fields": "userEnteredValue,userEnteredFormat,dataValidation"}},
    ]
    ws.spreadsheet.batch_update({"requests": requests})
    if ws.row_count < need:
        ws.add_rows(need - ws.row_count)
    ws.update(values=rows, range_name=f"A1:F{len(rows)}", value_input_option="USER_ENTERED")

    def rng(r0, r1, c0=0, c1=4):
        return {"sheetId": sid, "startRowIndex": r0, "endRowIndex": r1, "startColumnIndex": c0, "endColumnIndex": c1}

    requests = [
        {"repeatCell": {"range": rng(0, 1, 0, 6), "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                        "fields": "userEnteredFormat.textFormat.bold"}},
        {"updateSheetProperties": {"properties": {"sheetId": sid, "gridProperties": {"frozenRowCount": 1}},
                                   "fields": "gridProperties.frozenRowCount"}},
        {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 4, "endIndex": 6},
                                       "properties": {"hiddenByUser": True}, "fields": "hiddenByUser"}},
        {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
                                       "properties": {"pixelSize": 380}, "fields": "pixelSize"}},
    ]
    for h in headers:
        requests.append({"repeatCell": {"range": rng(h, h + 1),
                         "cell": {"userEnteredFormat": {"backgroundColor": YELLOW, "textFormat": {"bold": True}}},
                         "fields": "userEnteredFormat(backgroundColor,textFormat)"}})
    for r0, r1 in schools:
        if r1 > r0:
            requests.append(_validation(sid, r0, r1, 3, {"type": "BOOLEAN"}))
    ws.spreadsheet.batch_update({"requests": requests})


def write_pick(ws, keyword, shortlist):
    """Add (or replace) one blog's block at the bottom of the queue."""
    blocks = [b for b in read_queue(ws) if b["keyword"].lower() != keyword.lower()]
    blocks.append({"keyword": keyword, "schools": [
        {"name": s["name"], "count": s["count"], "volume": "", "approved": False}
        for s in shortlist[:MAX_SCHOOLS]]})
    render_queue(ws, blocks)


def set_ticks(ws, block, approved_rows):
    """Tick exactly the schools in approved_rows (sheet row numbers) for one blog's block."""
    tick_col = col_letter(QUEUE_HEADERS.index("✓") + 1)
    data = [{"range": f"{tick_col}{s['row']}", "values": [[s["row"] in approved_rows]]} for s in block["schools"]]
    if data:
        ws.batch_update(data, value_input_option="USER_ENTERED")


def archive_block(sh, keyword):
    """Move a processed blog's block from the queue to the archive tab."""
    ws = sh.worksheet(SCHOOLS)
    blocks = read_queue(ws)
    gone = [b for b in blocks if b["keyword"].lower() == keyword.lower()]
    if not gone:
        return
    append(sh.worksheet(ARCHIVE), [[keyword, s["name"], s["count"], s["volume"], "y" if s["approved"] else ""]
                                   for s in gone[0]["schools"]])
    render_queue(ws, [b for b in blocks if b["keyword"].lower() != keyword.lower()])


def set_volumes(ws, cells):
    """cells: [(row, volume)]. Writes straight into column C, so ticks aren't touched."""
    if not cells:
        return
    ws.batch_update([{"range": f"C{r}", "values": [[v]]} for r, v in cells], value_input_option="USER_ENTERED")
