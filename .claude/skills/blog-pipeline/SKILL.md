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

## 3. Choosing schools by search volume

The rule: every school with search volume 100 or more, highest first, at most 12. If fewer than 8 reach 100, top up with the next highest volumes until there are 8. Ties go to the school more competitor pages listed. `suggest` applies it; don't apply it by hand.

**a. Get volumes.** Run `python pipeline.py show --row "<kw>"` and paste the numbered lists. Ask for volumes, any way the user likes:
- **Screenshot** (Semrush or any tool): read each school name and volume off the image, match it to the numbered list by name (not by position), and show the matches before writing. A school not in the screenshot gets 0, say so.
- **Typed in chat** like `1: 320, 2: 90`.
- Either way, write them with `python pipeline.py setvol --row "<kw>" --vols "1:320, 2:90, 5:1500"`.
- **Semrush export file** in `data/semrush/`: run `python pipeline.py volumes`. `python pipeline.py names` prints the names to paste into Semrush.

**b. Suggest.** Run `python pipeline.py suggest --row "<kw>" ...` and paste the result. Mark top-ups clearly. Also flag anything worth a second look: government schools with codes in the name (GBSSS, GGSS, SKV), the same school listed twice under different names, a school that looks like it belongs to another area. Don't drop anything yourself. Ask "ok?" once for the whole batch.

**c. Approve.** On "ok", run `python pipeline.py approve --row "<kw>" --schools "<the selection line from suggest>"` per keyword. If the user changes one ("drop 9, add 12"), adjust that selection (it accepts `1-12 drop 4,7` style too). If approve refuses (fewer than 8, more than 12), show why and ask again.

Then go to step 4.

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

Then send `output/<slug>/blog.docx` and go to step 5. Don't stop at "the files are here".

## 5. Preview, then ask

**`blog.docx` is a PREVIEW, not the delivery.** Every run ends with the preview in the
user's hands and ONE question, then you stop:

> Draft this into the CMS, or do you want changes first?

Ask it even when QC passed, even when nothing looks wrong, and even when the user said
"write N blogs" and you have written all N. Finishing the write is not finishing the job.

**If they want changes** - edit `output/<slug>/blog.md`, rebuild the preview with
`python pipeline.py docx --row "<kw>"`, send it again and ask again. Loop until they say
draft it. Never run `draft` on a blog they have not just approved.

**If they say draft it** - run `python pipeline.py draft --row "<kw>"` (one `--row` per
approved blog). It uploads the images, converts the body to HTML with the shortcodes
intact, and creates an UNPUBLISHED draft. Then report per blog:
- the `edit_url`, so they can open it in their dashboard
- how many schools their CMS linked, against how many the blog has
- every `check:` line the command printed

A QC FAIL is never offered for drafting. Say what failed and ask what to do.

## Rules

- `draft` is as far as the pipeline goes: it creates an UNPUBLISHED draft. Never publish,
  never mark a row `published`. The last click is the user's, in their own dashboard.
- Never run `draft` unless the user approved that blog in this conversation. It writes to
  their live site.
- Never change `.env` or `WRITE_MODEL` unless asked.
- If a stage errors, the row keeps its status with an Error note. Show the error; rerunning the same stage retries only failures.
- Semrush volumes are optional and manual (`names`, then `volumes`). Mention them only if the user asks.
