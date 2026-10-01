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
`show` prints the numbered school list for picked blogs; `approve --row KW --schools "1-10"` ticks those and sets the blog to approved.
A failed row keeps its status and gets an Error note, so rerunning a stage retries only the failures.

## CMS

`CMS_MODE=fake` uses `data/fake_cms.json`. `CMS_MODE=api` needs `clients/cms_api.py`,
written once Yellow Slate shares the API docs.

Rules: name = school + area (board only for 2 campuses in one area, no short forms),
email = name letters only + `@gmail.com`, verified = No, claimed = No. Search always runs
before create, so reruns never duplicate. Every created school is logged in `data/cms_created.log`.

## Tests

`python -m pytest`
