"""Google Sheet control center. Same service-account pattern as the AIOS scripts/sheets.py.

The sheet is created by hand and shared (Editor) with the service account email,
because a service account can't own Drive files. Then `python pipeline.py setup`.

Tabs
  Blogs          one row per keyword, Status drives the pipeline
  Schools        Harshit's view: one 4-column block per blog (School | Count | Vol | ✓),
                 blogs side by side like his old tracker
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

BLOG_HEADERS = ["Keyword", "City", "Area", "Slug", "Status", "Error", "Live link", "Minutes", "Updated"]
CMS_HEADERS = ["Keyword", "School", "CMS name", "CMS ID", "CMS slug", "Created by us"]
STATUSES = ["new", "picked", "approved", "cms_done", "written", "qc_pass", "qc_fail", "published"]

# Schools view geometry
GROUP = ["School", "Count", "Vol", "✓"]
WIDTH = len(GROUP)
FIRST_ROW = 3           # row 1 keyword, row 2 sub-headers
MAX_SCHOOLS = 15
VIEW_ROWS = FIRST_ROW + MAX_SCHOOLS - 1


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
    for name, rows, cols in ((BLOGS, 1000, len(BLOG_HEADERS)), (SCHOOLS, VIEW_ROWS, WIDTH * 10),
                             (CMS, 10000, len(CMS_HEADERS)), (WEEKLY, 30, 4)):
        if name not in existing:
            existing[name] = sh.add_worksheet(title=name, rows=rows, cols=cols)

    for name, headers in ((BLOGS, BLOG_HEADERS), (CMS, CMS_HEADERS)):
        ws = existing[name]
        ws.update(values=[headers], range_name="A1")
        ws.freeze(rows=1)
        ws.format(f"A1:{col_letter(len(headers))}1", {"textFormat": {"bold": True}})
    existing[SCHOOLS].freeze(rows=2)

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
# Schools view: one column block per blog


def _grid(ws):
    values = ws.get_all_values()
    width = max([len(r) for r in values] + [0])
    return [r + [""] * (width - len(r)) for r in values] + [[""] * width] * max(0, VIEW_ROWS - len(values))


def read_picks(ws):
    """{keyword_lower: {"keyword", "col", "schools": [{"name", "count", "volume", "approved", "row"}]}}.
    "col" is the block's first column, 1-based."""
    grid = _grid(ws)
    if not grid:
        return {}
    out = {}
    for c in range(0, len(grid[0]), WIDTH):
        keyword = grid[0][c].strip()
        if not keyword:
            continue
        schools = []
        for r in range(FIRST_ROW - 1, min(len(grid), VIEW_ROWS)):
            name = grid[r][c].strip()
            if not name:
                continue
            schools.append({
                "name": name,
                "count": grid[r][c + 1],
                "volume": grid[r][c + 2].strip(),
                "approved": str(grid[r][c + 3]).strip().upper() == "TRUE",
                "row": r + 1,
            })
        out[keyword.lower()] = {"keyword": keyword, "col": c + 1, "schools": schools}
    return out


def write_pick(ws, keyword, shortlist):
    """Write one blog's block: reuses the keyword's block if it exists, else the first empty one."""
    picks = read_picks(ws)
    if keyword.lower() in picks:
        col = picks[keyword.lower()]["col"]
    else:
        used = [p["col"] for p in picks.values()]
        col = (max(used) + WIDTH) if used else 1
    last = col + WIDTH - 1
    if last > ws.col_count:
        ws.add_cols(last - ws.col_count + WIDTH * 10)
    if VIEW_ROWS > ws.row_count:
        ws.add_rows(VIEW_ROWS - ws.row_count)

    rows = [[keyword, "", "", ""], GROUP]
    for s in shortlist[:MAX_SCHOOLS]:
        rows.append([s["name"], s["count"], "", False])
    rows += [["", "", "", ""]] * (VIEW_ROWS - len(rows))
    rng = f"{col_letter(col)}1:{col_letter(last)}{VIEW_ROWS}"
    ws.update(values=rows, range_name=rng, value_input_option="USER_ENTERED")
    ws.format(f"{col_letter(col)}1:{col_letter(last)}2", {"textFormat": {"bold": True}})
    n = len(shortlist[:MAX_SCHOOLS])
    ws.spreadsheet.batch_update({"requests": [
        _validation(ws.id, FIRST_ROW - 1, FIRST_ROW - 1 + n, col + 2, {"type": "BOOLEAN"}),
    ]})


def set_volumes(ws, cells):
    """cells: [(row, block_col, volume)]. Writes into the Vol column of each block."""
    if not cells:
        return
    data = [{"range": f"{col_letter(c + 2)}{r}", "values": [[v]]} for r, c, v in cells]
    ws.batch_update(data, value_input_option="USER_ENTERED")
