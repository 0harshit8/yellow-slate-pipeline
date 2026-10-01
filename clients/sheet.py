"""Google Sheet control center. Same service-account pattern as the AIOS scripts/sheets.py.

The sheet is created by hand and shared (Editor) with the service account email,
because a service account can't own Drive files. Then `python pipeline.py setup`.
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
WEEKLY = "Weekly review"

BLOG_HEADERS = ["Keyword", "City", "Area", "Slug", "Status", "Error", "Live link", "Minutes", "Updated"]
SCHOOL_HEADERS = ["Keyword", "School", "Competitor count", "Sources", "Approve",
                  "Semrush volume", "CMS ID", "CMS slug", "Created by us"]

STATUSES = ["new", "picked", "approved", "cms_done", "written", "qc_pass", "qc_fail", "published"]


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
    """Builds the 3 tabs. Safe to re-run: only creates what's missing and rewrites headers."""
    existing = {w.title: w for w in sh.worksheets()}
    if BLOGS not in existing and "Sheet1" in existing:
        existing["Sheet1"].update_title(BLOGS)
        existing[BLOGS] = existing.pop("Sheet1")
    for name, rows, cols in ((BLOGS, 1000, len(BLOG_HEADERS)), (SCHOOLS, 15000, len(SCHOOL_HEADERS)), (WEEKLY, 30, 4)):
        if name not in existing:
            existing[name] = sh.add_worksheet(title=name, rows=rows, cols=cols)

    for name, headers in ((BLOGS, BLOG_HEADERS), (SCHOOLS, SCHOOL_HEADERS)):
        ws = existing[name]
        ws.update(values=[headers], range_name="A1")
        ws.freeze(rows=1)
        ws.format(f"A1:{col_letter(len(headers))}1", {"textFormat": {"bold": True}})

    blogs_ws, schools_ws = existing[BLOGS], existing[SCHOOLS]
    approve_col = SCHOOL_HEADERS.index("Approve")
    status_col = BLOG_HEADERS.index("Status")
    sh.batch_update({"requests": [
        _validation(schools_ws.id, approve_col, {"type": "BOOLEAN"}),
        _validation(blogs_ws.id, status_col, {
            "type": "ONE_OF_LIST", "values": [{"userEnteredValue": s} for s in STATUSES]}),
    ]})

    # Weekly review: formulas only, so it's always current for the call.
    week_start = "TODAY()-WEEKDAY(TODAY(),2)+1"
    grid = [
        ["Weekly review", "", "", ""],
        ["", "This week", "Total", "Target"],
        ["Blogs published",
         f'=COUNTIFS(Blogs!E:E,"published",Blogs!I:I,">="&{week_start})',
         '=COUNTIF(Blogs!E:E,"published")', 600],
        ["Schools added to CMS", "", '=COUNTIF(Schools!I:I,"y")', ""],
        ["Avg minutes per blog", "", '=IFERROR(AVERAGE(Blogs!H2:H),"")', 15],
        ["", "", "", ""],
        ["Status", "Blogs", "", ""],
    ] + [[s, f'=COUNTIF(Blogs!E:E,"{s}")', "", ""] for s in STATUSES]
    existing[WEEKLY].update(values=grid, range_name="A1", value_input_option="USER_ENTERED")
    existing[WEEKLY].format("A1:D2", {"textFormat": {"bold": True}})


def _validation(sheet_id, col, condition):
    return {"setDataValidation": {
        "range": {"sheetId": sheet_id, "startRowIndex": 1, "startColumnIndex": col, "endColumnIndex": col + 1},
        "rule": {"condition": condition, "strict": True, "showCustomUi": True},
    }}


def records(ws):
    """Rows with a Keyword, as dicts keyed by header, each with "_row" (1-based sheet row).

    Blank rows are skipped: the checkbox column pre-fills FALSE on every row, so
    "has any value" doesn't mean "is a real row".
    """
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
    """Write rows starting at the first row with an empty column A.

    Not ws.append_rows: Sheets' append skips past rows that only hold a FALSE
    checkbox, which would drop new rows at the very bottom of the tab.
    """
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
    """Write {header: value} into one row, one call per contiguous cell."""
    data = [{"range": f"{col_letter(headers.index(k) + 1)}{row}", "values": [[v]]} for k, v in fields.items()]
    ws.batch_update(data, value_input_option="USER_ENTERED")


def set_blog(ws, row, status=None, error="", **extra):
    fields = {"Error": error, "Updated": datetime.now().strftime("%Y-%m-%d %H:%M")}
    if status:
        fields["Status"] = status
    fields.update(extra)
    update(ws, BLOG_HEADERS, row, fields)


def is_ticked(value):
    return str(value).strip().upper() == "TRUE"
