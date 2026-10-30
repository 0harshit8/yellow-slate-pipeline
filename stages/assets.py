"""Parent review graphs, done in Python after the writer finishes.

The headless writer can't run shell commands, so it only records what's needed:
  - assets.json: {"schools": [{"name", "slug", "reviews": {category: [pos, neg]}}]}
  - placeholders in blog.md: <!-- GRAPH: slug -->
This step draws each graph with Yellow Slate's own chart script and swaps the placeholders
for markdown images. Anything that fails is dropped from the blog and listed in notes.md,
so QC and the human review see it.

School photos are added by hand after the blog is written; nothing here fetches one.
download_image and shrink are kept for that manual path, not called by process().
"""

import importlib.util
import json
import os
import re

import requests

import config

CHART_SCRIPT = os.path.join(config.ROOT, ".claude", "skills", "yellow-slate-seo-writer", "scripts",
                            "generate_review_chart.py")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
EXT = {"image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
MIN_BYTES = 5000  # anything smaller is a logo, icon or error page
# Their media endpoint refuses a file over 5 MB, and schools publish 5120x2880 originals.
# An image that arrives too big is shrunk rather than dropped: the alternative is a draft
# that silently carries a local path where a photo should be.
MAX_BYTES = 4_500_000
MAX_SIDE = 1920   # a blog card never needs more


def download_image(url, dest_base):
    """Returns the saved file name, or raises ValueError with the reason."""
    r = requests.get(url, headers=UA, timeout=30)
    if not r.ok:
        raise ValueError(f"HTTP {r.status_code}")
    ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
    if ctype not in EXT:
        raise ValueError(f"not an image ({ctype or 'no content-type'})")
    if len(r.content) < MIN_BYTES:
        raise ValueError(f"too small ({len(r.content)} bytes)")
    path = dest_base + EXT[ctype]
    with open(path, "wb") as fh:
        fh.write(r.content)
    if len(r.content) > MAX_BYTES:
        path = shrink(path)
    return os.path.basename(path)


def shrink(path):
    """Resize an oversized photo so their media endpoint will take it. Returns the new path.

    A PNG photograph often will not fit under the limit as a PNG at any sane size, so it is
    re-saved as a JPEG and the original removed -- the caller uses the returned name.
    shortcut: transparency is dropped, which is wrong for a logo but these are photographs,
    and MIN_BYTES has already excluded the icon-sized files. Revisit if a school ever
    publishes a transparent campus shot.
    """
    from PIL import Image

    with Image.open(path) as im:
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        im.thumbnail((MAX_SIDE, MAX_SIDE))
        im.save(path, quality=85, optimize=True)
        if os.path.getsize(path) <= MAX_BYTES:
            return path
        jpg = os.path.splitext(path)[0] + ".jpg"
        im.save(jpg, "JPEG", quality=80, optimize=True)
    if jpg != path:
        os.remove(path)
    return jpg


_chart_fn = None


def _chart():
    """Their generate_chart(), imported from the skill's script.

    Imported, not run as a command: the script's argparse help contains a bare '%',
    which Python 3.14 rejects at startup. Their file stays unchanged.
    """
    global _chart_fn
    if _chart_fn is None:
        spec = importlib.util.spec_from_file_location("ys_review_chart", CHART_SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _chart_fn = mod.generate_chart
    return _chart_fn


def draw_graph(name, reviews, dest):
    try:
        _chart()(name, {k: list(v) for k, v in reviews.items()}, dest)
    except Exception as err:  # their script, any failure is a graph problem not a crash
        raise ValueError(f"{type(err).__name__}: {err}"[:200])
    if not os.path.exists(dest):
        raise ValueError("chart script wrote no file")


def valid_reviews(reviews):
    """Shaped right AND carrying at least one non-zero number.

    An all-zero set is not thin data, it is no data: the Kolar run published nine schools at
    0/0 across every category and the chart script drew nine titled, axis-labelled, empty
    frames. QC passed them, because it only asks whether a graph image exists. A school with
    no review signal at all belongs out of the blog, not in it behind a blank chart.
    """
    return bool(_shaped(reviews) and any(x for v in reviews.values() for x in v))


def _shaped(reviews):
    return isinstance(reviews, dict) and reviews and all(
        isinstance(v, (list, tuple)) and len(v) == 2 and all(isinstance(x, (int, float)) for x in v)
        for v in reviews.values())


def all_zero_reviews(reviews):
    """Shaped like review data but every number is 0 — told apart from malformed data so
    notes.md can say which of the two happened."""
    return bool(_shaped(reviews) and not any(x for v in reviews.values() for x in v))


def process(folder):
    """Fill images + graphs for one blog folder. Returns a list of problems (empty = all good)."""
    blog_path, assets_path = os.path.join(folder, "blog.md"), os.path.join(folder, "assets.json")
    if not os.path.exists(assets_path):
        return ["no assets.json from the writer"]
    with open(assets_path, encoding="utf-8") as fh:
        assets = json.load(fh).get("schools", [])
    with open(blog_path, encoding="utf-8") as fh:
        md = fh.read()

    os.makedirs(os.path.join(folder, "images"), exist_ok=True)
    os.makedirs(os.path.join(folder, "graphs"), exist_ok=True)
    problems = []
    for s in assets:
        slug, name = s.get("slug", ""), s.get("name", "")
        graph_tag = f"<!-- GRAPH: {slug} -->"

        replacement = ""
        if valid_reviews(s.get("reviews")):
            try:
                draw_graph(name, s["reviews"], os.path.join(folder, "graphs", f"{slug}.png"))
                replacement = f"![Parent sentiment breakdown for {name}](graphs/{slug}.png)"
            except ValueError as err:
                problems.append(f"{name}: graph failed ({err})")
        elif all_zero_reviews(s.get("reviews")):
            problems.append(f"{name}: every category is 0, so there is no review signal and no "
                            f"graph. Replace this school or publish it without a graph.")
        else:
            problems.append(f"{name}: no category review percentages, no graph")
        md = md.replace(graph_tag, replacement)

    md = re.sub(r"<!-- (IMAGE|GRAPH): [^>]* -->\n?", "", md)  # placeholders with no assets entry
    md = re.sub(r"\n{3,}", "\n\n", md)
    with open(blog_path, "w", encoding="utf-8") as fh:
        fh.write(md)
    if problems:
        with open(os.path.join(folder, "notes.md"), "a", encoding="utf-8") as fh:
            fh.write("\n\n## Pipeline: graphs\n\n" + "\n".join(f"- {p}" for p in problems) + "\n")
    return problems
