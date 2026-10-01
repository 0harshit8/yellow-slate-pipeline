"""Read Semrush Keyword Overview exports (bulk analysis) into {term: volume}.

Semrush names its export .xlsx even when it's CSV text, so both are handled:
real .xlsx via openpyxl, everything else parsed as CSV.
"""

import csv
import glob
import io
import os
import zipfile

from clients.dataforseo import clean


def _rows(path):
    if zipfile.is_zipfile(path):
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        return [[("" if c is None else str(c)) for c in r] for r in wb.worksheets[0].iter_rows(values_only=True)]
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        return list(csv.reader(io.StringIO(fh.read())))


def _volume(text):
    text = str(text).strip().replace(",", "")
    if not text or text.lower() in ("n/a", "-"):
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def semrush_volumes(folder):
    """{clean(keyword): volume} from every .csv / .xlsx export in folder."""
    out = {}
    for path in sorted(glob.glob(os.path.join(folder, "*.csv")) + glob.glob(os.path.join(folder, "*.xlsx"))):
        rows = _rows(path)
        if not rows:
            continue
        header = [h.strip().lower() for h in rows[0]]
        if "keyword" not in header:
            continue
        k = header.index("keyword")
        v = next((i for i, h in enumerate(header) if h == "volume" or h.startswith("volume")), None)
        if v is None:
            continue
        for row in rows[1:]:
            if len(row) <= max(k, v):
                continue
            vol = _volume(row[v])
            if vol is not None and clean(row[k]):
                out[clean(row[k])] = vol
    return out
