# Browser top-up pass — design

## What problem this solves

A fact sheet has ~24 fields. The headless researcher gets nearly all of them right. Three it
structurally cannot get:

| Field | Why WebFetch fails |
|---|---|
| `REVIEWS` | Justdial serves 403 to a direct fetch. `.claude/agents/school-researcher.md:25` already says so, and the agent has no tool that gets past it. |
| `FEES` | Some schools publish the table only as a scanned PDF or a JPEG. Text extraction returns nothing. |
| `IMAGE_URL` | Deciding whether a photo shows the building or a prize-giving is a visual judgement. WebFetch reads text. |

Measured on Gwalior (12 schools): 6 had `REVIEWS: NOT_FOUND` while Justdial held 80-185
ratings for every one. 11 of 12 had no confirmed building photo. 2 fee tables were
unreadable scans.

So this pass repairs **three fields**, not whole schools. Routing every school through a
browser to fix three fields would be paying full price for a partial repair.

## Where it runs, and why it cannot be a normal stage

`clients/claude_cli.py` runs every LLM step as `claude -p --strict-mcp-config`. That flag
skips all MCP servers, and the browser *is* an MCP server belonging to the desktop app. A
headless subprocess has no browser pane. Adding browser tools to an agent's frontmatter
would do nothing there.

So the pass splits in two:

- **Python side** — finds the work, applies the results. No LLM, no browser. Testable.
- **Desktop side** — a session with the browser pane spawns browser subagents.

The join between them is a JSON worklist and a JSON patch. Nothing else couples them.

## Prerequisites (ship before any bulk run)

**P1. Record a block as a block.** In `school-researcher.md`, a 403 must write
`REVIEWS: BLOCKED | <url>` rather than `NOT_FOUND`. Without this you cannot tell a wall from
a school that genuinely has no reviews, and the top-up has no worklist to build from. This is
the single highest-value line in the whole design.

**P2. Stop caching sheets known to be broken.** Finding 3 of the earlier review, still open:
`research.collect` flags a partial sheet and `research.save_to_store` stores it anyway, so the
next blog reuses it and spawns no researcher to repair it. At 3,650 schools a bad batch
becomes 90 days of silently wrong blogs. Fix: run each file through the existing `_entry`
helper in `save_to_store` and skip the ones it flags.

## 1. `pipeline.py topup --row KEYWORD [--limit N]` — build the worklist

Pure Python, in `stages/topup.py`. Reads the sheets for that keyword's schools and writes
`output/<slug>/topup.json`:

```json
[{"id": "18889", "name": "ITM Global School", "city": "Gwalior", "area": "Turari",
  "needs": ["reviews", "image"],
  "urls": {"reviews": "<the BLOCKED url, if P1 recorded one>", "site": "<PROFILE_URL>"}}]
```

A field needs top-up when:

- `reviews` — `REVIEWS` is missing, `NOT_FOUND`, or `BLOCKED`
- `fees` — `FEES` is missing or `NOT_FOUND`, **or** `FEES_NOTE` names a scan/PDF that would
  not render
- `image` — `IMAGE_URL` is missing, `NONE`, or `NOT_FOUND`, and the run's photo budget still
  has room (§6)

## 2. `.claude/agents/school-topper.md` — the browser researcher

`tools: navigate, get_page_text, computer, javascript_tool, find, tabs_create, tabs_close`

Up to four schools per invocation, worked one at a time. Returns an **array of patches**,
one object per school — only the fields it found — never a whole sheet, so it cannot clobber
good data. `read_patches` already accepts that array shape, so batching is a prompt change
and no code change. The cost of batching is shared fate: an agent that stops early takes
the schools it had not reached with it, so it is told to return what it finished.

See §6 for why this is the lever that matters.

**Tab discipline, non-negotiable:** open your own tab with `tabs_create`, work only in that
`tabId`, close it when done. During testing a subagent navigated the main session's tab out
from under it mid-task. With several researchers running this is the normal case, not an
edge case.

**Reviews.** Open the Justdial listing, `get_page_text` with `max_chars: 20000` — the page
is huge and the 50,000 default is mostly navigation. Capture the rating, the ratings
count, the "Key Insights" liked/improve block, and every visible review text. Derive the six
category pos/neg splits. Write `REVIEWS_BASE` honestly — "4.4 over 185 ratings, 10 texts
read" — because the count and the readable text are usually very different numbers.

**Fees.** Open the PDF or image URL, screenshot it at `scale: 0.5`, read the table
visually. `FEES_SOURCE`
becomes the school's own document rather than an aggregator.

**Image.** Work the rungs in order: the school's own site (list images ≥600px wide with
`javascript_tool`, including `alt` and natural dimensions), then its gallery, campus-tour
and infrastructure pages, then any carousel that only fills in on interaction — the one
rung a headless fetch cannot reach at all — then the school's own Facebook or Instagram,
then another branch of the same school. Open the best candidate and *look* at it; `scale:
0.5` is plenty, and a quarter of the tokens. Confirm it shows the building or campus — not
a ceremony, class group or logo. Never a directory, an aggregator or Google Maps: Yellow
Slate re-hosts the file, so it has to be the school's own
(`.claude/agents/school-researcher.md` holds the operative wording).


## 3. `pipeline.py topup --apply` — merge back

`stages/topup.py` merges the patch into `data/research/<id>.md`:

- replaces only the named fields; every other byte is left alone
- re-parses the result and **refuses to write** a sheet that no longer parses
- refreshes mtime, which is correct here: the data is genuinely newer
- adds a `TOPUP:` provenance line so topped-up fields are distinguishable later

## 4. Concurrency and politeness

- At most 3 browser agents at once, four schools each. The box is 8GB and the repo notes
  say runs are already memory-bound.
- One tab per agent, reused across its schools and closed on exit.
- A pause between Justdial loads; `--limit` caps a run.
- If a page returns a block page, record `BLOCKED` again and **stop that run** rather than
  retrying. Do not escalate against a site that is asking you to stop.

## 5. Tests

- round trip: parse → patch → parse leaves every untouched field byte-identical
- a patch that would break parsing is refused, and the sheet on disk is unchanged
- a sheet with no `needs` produces no worklist entry

## 6. What a run costs, and the two levers

Measured over 14 topper agents: the cheapest run was 6 tool calls for 71,855 tokens, the
dearest 62 calls for 107,332. Ten times the work for 49% more tokens, which fits a fixed
cost of ~68,000 tokens per agent plus ~630 per tool call. Across those 14 agents the fixed
floor was ~950k of 1.21M — **79% of the spend bought agent start-ups, not research.**

So the lever is fewer agents, not cheaper ones:

- **Batching** (§2). Four schools per agent pays the floor once. On paper 11 schools in 3
  agents takes 1.21M to ~400k; expect nearer half that in practice, because a batched agent
  carries each school's pages in its context as it goes, so school four costs more than
  school one.
- **Smaller reads.** `max_chars` on `get_page_text` and `scale: 0.5` screenshots.

Re-reading the agent definition is *not* a lever: 984 words plus the prompt is ~1,800 tokens
of an 80,000-token run, about 2%.

**The photo budget.** The whole photo hunt for one run is capped at 3,000,000 tokens —
`IMAGE_BUDGET` in `stages/topup.py`. Nothing in the pipeline can count a subagent's real
tokens, so the budget is spent in the unit this code can count: schools sent looking for a
photo. At ~62,000 a school (~40,000 of researcher margin, ~17,000 of agent start-up share,
~5,000 of tool calls) that is about 48 schools, or four blogs' worth, per run. One blog is
8-12 schools and never reaches it; a city sweep across several keywords does, and then the
run drops the `image` group from the remaining worklists and prints what it left out.
Reviews and fees are never dropped: they are what this pass exists for, and a photo can be
added by hand.

**Haiku: not yet, and not everywhere.** The image call is close to a perceptual yes/no
against one clear rule, so it is the plausible candidate. Fees and reviews are not: they
turn on telling The Scindia School from Scindia Kanya Vidyalaya, picking the right one of
three Justdial listings for Pearls Valley, and adding line items back up under a stamp that
hides the total. Note also that the two good image calls so far were *rejections* — a
reception of dignitaries, and a student portrait with the building blurred behind — which
needed strictness rather than willingness to accept something plausible. Sonnet already
produced two bad category splits here; haiku would more likely be worse at exactly that.
So: try it on image-only batches, compare a few against what sonnet found, and keep the
"say what the photo shows before you accept it" instruction so a weak judgement stays
visible.

## Scale

Run per city, when you are about to write that city's blogs — not as one 3,650-school
migration. Sheets cache for 90 days and no city has more than 3 keywords, so a city is paid
for once and reused by its remaining keywords.

481 pending keywords sit across 268 cities. 101 of those cities have a single keyword and get
no reuse at all, so the cache saves roughly a third of the work, not most of it.

## What this does not fix

- **Justdial throttling at volume.** Thousands of page loads from one IP will be noticed.
  Untested, and it is the risk most likely to sink the approach. It applies equally to a
  Playwright version, so it is not a reason to prefer one over the other.
- Schools with genuinely no reviews anywhere.
- Google Maps — never tested here; totals may be higher than Justdial alone.
- It is not unattended. That is the real price: roughly 300 sessions for the full backlog.
