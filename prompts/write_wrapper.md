Use the yellow-slate-seo-writer skill to write one blog. This is a batch run with no human in the loop, so follow these overrides to the skill:

1. **Requirements are already gathered (Step 1).** Don't ask for anything.
   - Primary keyword: {keyword}
   - Blog type: Listicle
   - City: {city}
   - Area: {area}
   - Blog URL slug: {slug}
   - Schools, in this order:
{schools}
2. **School URLs and IDs are given above (Step 2.5).** Use them exactly. Don't look these schools up in schools.csv and don't ask which branch. The admissions shortcode for each school is `[btn_admissions id="<CMS ID>"]` and the first bullet links the school name to its profile URL. For internal links (Step 2.7), web-search `site:yellowslate.com/blog` — **don't open
   schools.csv at all.** It is a 5 MB file, and the search is both cheaper and more current.
   Those one or two searches are the only web work you do yourself; everything else is the
   researchers' job.
3. **Outline approval is pre-granted (Step 3).** Don't stop to present the outline. Go straight to writing.
4. **Research is done by subagents, not by you.** For each school, spawn a
   `school-researcher` subagent (the `Agent` tool, `subagent_type: "school-researcher"`). It
   already knows the source order, the query shapes, the verification rule and the search
   budget, so **the prompt you send it must contain only that school's data and nothing else**:

   ```
   SCHOOL: <name>
   LOCALITY: <area>, <city>
   CMS_ID: <id>
   PROFILE_URL: <url>
   DIRECTORY_RATINGS: <the "Directory ratings" value from the list above>
   ```

   `DIRECTORY_RATINGS` is how many parent ratings stage 1 counted for that school on a
   directory page it already read. It is evidence the listing exists, and the researcher
   knows what to do with it. Copy the number across exactly, or `NONE`.

   **Don't pass a model when you spawn them.** The researchers run on a stronger model than you
   do, set in their own definition, because their half of the job is the one nothing checks
   afterwards. A model you pass in the spawn call would override that and quietly downgrade them.

   Send no instructions, no reminders, no context about the blog. Every researcher must receive
   a byte-identical prompt apart from those four values. That is not a style preference: the
   subagents share one cached prefix, and any wording you add in front of the data breaks it and
   makes each one pay full price again.

   **Dispatch order matters.** Spawn the **first school alone and wait for it to finish.** Then
   spawn the rest **three or four at a time**, waiting for each group. A cached prefix only
   becomes readable once the first response has started, so firing all twelve at once means none
   of them can read it and all twelve are charged in full. One, then groups of three or four.

   **What to do with what comes back.** Each fact sheet ends with `GAPS` and `CONFLICTS`. Copy
   both into notes.md verbatim. Then:
   - A field marked `OMIT` or `NOT_FOUND` -> **omit that table row.** Don't fill it with a
     fallback sentence, and don't go looking yourself — the researcher already spent its budget.
   - `FEES` with an annual figure and `FEES_NOTE` saying class-wise isn't published -> publish
     the figure and say class-wise numbers aren't published. Do **not** write "contact the
     school" when you have a figure.
   - `FEES: NOT_FOUND` -> this is one of the few places "Contact the school for the latest
     details." is correct. Same for current-cycle admission dates and seat vacancies.
   - `CONFLICTS` with two values -> publish the registry value and note the conflict in notes.md.
   - `VERIFIED_VIA: NONE` -> flag that school prominently in notes.md. Its facts are unconfirmed.
   - `REVIEWS: NOT_FOUND` -> **leave that school's `reviews` out of assets.json entirely.**
     Never write `[0, 0]`, and never write a category you have no number for. Zero is not a
     thin measurement, it is no measurement, and the pipeline draws it as an empty graph.
   - `NO_EVIDENCE: YES` -> the school has neither fees nor reviews on record. Write its
     section from what the registry does give, and list it under a `## Swap these schools`
     heading at the top of notes.md with what the researcher tried. A human replaces it with
     a better-documented school rather than publishing a section with two holes in it.

   Never add a fact no fact sheet contains. You did not do this research and cannot check it.

   **If the `school-researcher` subagent type does not exist**, stop and reply
   `FAILED: school-researcher agent not found`. Do **not** fall back to researching the schools
   yourself and do **not** substitute a general-purpose agent — both quietly undo the reason this
   stage uses subagents, and the run would look like a success. As the first line of notes.md,
   write `researcher: school-researcher x <n> schools, <total> searches` from the fact sheets'
   `SEARCHES_USED` values, so a human can see the real agent ran.
5. **Length: aim for {budget} words of prose and treat it as a ceiling, not a target to beat.**
   That is the skill's formula (about 250-300 words per school plus intro, conclusion and FAQ)
   for this school count. You have no shell, so don't count words yourself — but do keep each
   school's section to roughly 250-300 words as you go, rather than writing long and hoping.
   QC fails the blog above 1.5x this number, which means a full rewrite, so staying near it is
   cheaper for everyone. Depth belongs in which facts you found, not in more words about them.
6. **Images and graphs are handled by the pipeline after you finish. Don't download images, don't run any shell commands and don't draw charts.** Instead:
   - In blog.md, put `<!-- IMAGE: <school-slug> -->` on its own line where each school's image goes (after the 3 intro bullets, before the info table), and `<!-- GRAPH: <school-slug> -->` on its own line where each school's parent review graph goes (after the review bullets). `<school-slug>` is the school name lowercased and hyphenated.
   - Don't add a markdown fallback table for the graph. The graph replaces it.
   - Write `{out_dir}/assets.json`:
     `{{"schools": [{{"name": "<school name>", "slug": "<school-slug>", "image_url": "<direct URL of a campus photo on the school's official website, or null>", "reviews": {{"<Category>": [<positive %>, <negative %>], "...": [0, 0]}}}}]}}`
     The review percentages must match the percentages in the blog text exactly.
     Every school whose fact sheet carries any review signal gets category percentages and a
     graph, no matter how thin or contradictory the base — derive them from whatever exists
     (aggregate rating, a handful of written reviews, follower and shortlist counts) and say in
     the review bullets that the base is small. A thin base is a caveat to state, never a reason
     to omit the percentages or the graph.
     **The one exception is a fact sheet that says `REVIEWS: NOT_FOUND`.** Then omit that
     school's `reviews` key and its `<!-- GRAPH: -->` placeholder, write in the review bullets
     that no parent reviews are published for this school yet, and list it under
     `## Swap these schools` in notes.md. Never fill the gap with zeros: a `[0, 0]` category is
     published as an empty bar, and a school whose every category is 0 produced a titled,
     axis-labelled, blank graph nine times in the Kolar blog. Omit a category you have no
     number for rather than zeroing it.
7. **Save into the folder `{out_dir}`** (relative to the current directory):
   - `{out_dir}/blog.md`. No H1 title in the file: it starts with the introduction paragraph, as the skill says.
   - `{out_dir}/meta.json` with keys `title`, `meta_title`, `meta_description`, `slug` (use the slug given above; primary keyword in title and meta_title).
   - `{out_dir}/assets.json` as above.
   - `{out_dir}/notes.md`: a short list of missing data, conflicting sources and anything a human should check before publishing.
8. **Only read files in the skill folder and in `{out_dir}`.** Don't open, list or search other folders under `output/` or `data/`: they hold other blogs and old runs, and copying from them mixes up schools.
9. Run the skill's quality checklist yourself before finishing (images and graphs excepted, the pipeline adds them).

When done, reply with one line: DONE or FAILED: <reason>.
