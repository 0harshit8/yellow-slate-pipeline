# Yellow Slate blog pipeline

Turns a keyword like "schools in Kalkaji" into a publish-ready Yellow Slate listicle.
The Google Sheet is the control center. Each stage moves rows to the next status.

```
new -> pick -> picked -> (you tick 8-12 schools, set approved) -> cms -> cms_done
    -> write -> written -> qc -> qc_pass / qc_fail -> (you review + publish) -> published
```

## One-time setup

1. `pip install gspread google-auth requests pytest` (already installed on Harshit's machine)
2. Copy `.env.example` to `.env` and fill it in.
3. Put Yellow Slate's 4 reference files in `.claude/skills/yellow-slate-seo-writer/references/`:
   `tone-of-voice.md`, `schools.csv`, `content-structure-listicle.md`, `example-blogs.md`
4. Create a Google Sheet, share it (Editor) with the service account email in your key file,
   put its ID in `.env` as `SHEET_ID`, then run `python pipeline.py setup`.

## From chat (easiest)

Open Claude Code in this folder and talk to it. The `blog-pipeline` skill adds keywords, asks which
ones to work on, shows each school list numbered so you choose in chat ("1-12 drop 4,7"), then runs
volumes (screenshot, typed, or Semrush export), picks schools by the volume rule for you to ok, runs
cms, write and qc straight through and reports QC, time and cost per blog. You never edit the sheet.

## Daily use

```
python pipeline.py add "schools in Kalkaji" --city Delhi     # or paste rows into the Blogs tab with status "new"
python pipeline.py pick  --limit 25      # ~45 sec a keyword
#   -> Schools tab: check Semrush volumes, tick 8-12, set the blog's Status to "approved"
python pipeline.py cms   --limit 25
python pipeline.py write --limit 5       # slowest stage, run in batches
python pipeline.py qc
python pipeline.py status
```

Every stage takes `--row "<keyword>"` (repeatable, for several keywords) and `--limit N`. `add` takes several keywords at once.
`show` prints the numbered school list for picked blogs; `setvol --row KW --vols "1:320, 2:90"` writes volumes; `suggest` applies the volume rule (100+, highest first, max 12, top up to 8); `approve --row KW --schools "1-10"` ticks those and sets the blog to approved.
A failed row keeps its status and gets an Error note, so rerunning a stage retries only the failures.

## CMS

`CMS_MODE=fake` uses `data/fake_cms.json`. `CMS_MODE=api` talks to their live CMS through
`clients/cms_api.py`. `BLOG_MODE=api` also pushes unpublished drafts; `off` means you paste
`blog.docx` in by hand. Run `python verify_ys_api.py` before a batch to check their API.

Rules: name = the plain school name, no area (their API appends the area to the slug itself),
no short forms. Verified = No, claimed = No. Search always runs before create, so reruns
never duplicate. Every created school is logged in `data/cms_created.log`.

**Area is per school, not per keyword.** Their API demands a name, a city and an area on
every lookup, with no city-wide search, and an area named after its own city is a real but
empty area that matches nothing. So a city keyword like "best schools in Lucknow" has no
single area to use: the pick stage reads each school's locality off the competitor pages,
`stages/area.py` checks it against their CMS, and the CMS stage files each school under its
own locality. A school whose area cannot be resolved is dropped from the blog with a note,
and the blog stops if that leaves fewer than 8. The Area column in the Schools tab is
editable, so filling it by hand overrides everything.

`python preflight_keywords.py keywords.csv` checks a whole keyword list's cities and areas
up front.

## Tests

`python -m pytest`
