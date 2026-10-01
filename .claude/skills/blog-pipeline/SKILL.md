---
name: blog-pipeline
description: Run the Yellow Slate "Schools in [Area]" blog pipeline from chat. Use when the user gives keywords to add, asks what is waiting, asks to pick or approve schools, asks to write N blogs or specific keywords, or asks for pipeline status. Trigger on "add these keywords", "write blogs", "what's pending", "pick schools", "run the pipeline".
---

# Blog pipeline from chat

The user never edits the Google Sheet. You run `python pipeline.py ...` from the repo root and the sheet stays the record. Each command only touches rows in the status before it (see the docstring at the top of `pipeline.py`). `--row "<keyword>"` can be repeated to cover several keywords; always pass the exact keyword text from the sheet.

## 1. Adding keywords

User pastes keywords (a list, one per line, or comma separated).

- If no city was given, ask for it. One city per add command; group keywords by city.
- Run `python pipeline.py add "<kw1>" "<kw2>" ... --city <City>`. Area comes from the text after "in".
- Report what was added and what was skipped as a duplicate. Then go to step 2.

## 2. Choosing what to work on

Run `python pipeline.py status`. Show the counts in one line, for example "12 new, 2 picked waiting for schools, 1 written".

- If blogs are already `picked`, offer those first (go to step 3).
- For `new` rows, ask which keywords or how many. "first 5" means the first 5 `new` rows in sheet order.
- Run `python pipeline.py pick --row "<kw>" --row "<kw>" ...`. About 1 minute per keyword. Report any keyword that errored and why.

## 3. Choosing schools (in chat)

Run `python pipeline.py show --row "<kw>"` for each picked keyword and paste the numbered list as is. Ask the user to choose 8-12, accepting replies like `1-10`, `1-12 drop 4,7`, `all drop 3`.

- Before they answer, flag anything worth a second look: government schools with codes in the name (GBSSS, GGSS, SKV), the same school listed twice under different names, a school that looks like it belongs to another area. Do not drop anything yourself.
- Run `python pipeline.py approve --row "<kw>" --schools "<their reply>"`. If it refuses (fewer than 8, more than 12, bad numbers), show the message and ask again.
- Go through every picked keyword the user wants written, then go to step 4.

## 4. Running straight through

For the approved keywords, run this as ONE background command and tell the user it is running and roughly how long (10-15 min per blog, one at a time):

```
python pipeline.py cms --row "<kw>" ... && python pipeline.py write --row "<kw>" ... && python pipeline.py qc --row "<kw>" ...
```

Don't ask before each stage. While it runs, don't edit the sheet's Schools tab.

When it finishes, report one line per blog:
- QC result (PASS, or the FAIL lines from `output/<slug>/qc.txt`)
- minutes and cost from `output/<slug>/run.json` (`duration_ms`, `total_cost_usd`)
- anything in `output/<slug>/notes.md` a human must check before publishing (schools that could not be verified, conflicting fees, a live page already at the same URL)

Then say where the files are: `output/<slug>/blog.docx` to share, `blog.md` as the source.

## Rules

- Never publish, never mark a row `published`. Publishing is manual.
- Never change `.env` or `WRITE_MODEL` unless asked.
- If a stage errors, the row keeps its status with an Error note. Show the error; rerunning the same stage retries only failures.
- Semrush volumes are optional and manual (`names`, then `volumes`). Mention them only if the user asks.
