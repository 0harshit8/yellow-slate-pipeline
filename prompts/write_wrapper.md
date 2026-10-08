Use the yellow-slate-seo-writer skill to write one blog. This is a batch run with no human in the loop, so follow these overrides to the skill:

1. **Requirements are already gathered (Step 1).** Don't ask for anything.
   - Primary keyword: {keyword}
   - Blog type: Listicle
   - City: {city}
   - Area: {area}
   - Blog URL slug: {slug}
   - Schools, in this order:
{schools}
2. **School URLs and IDs are given above (Step 2.5).** Use them exactly. Don't look these schools up in schools.csv and don't ask which branch. The admissions shortcode for each school is `[btn_admissions id="<CMS ID>"]` and the first bullet links the school name to its profile URL. You may still use schools.csv to find internal links (Step 2.7).
3. **Outline approval is pre-granted (Step 3).** Don't stop to present the outline. Go straight to writing.
4. **Missing data: work the source order before you fall back.** Never invent data, but don't
   reach for "Contact the school" either. Step 2.4 of the skill gives a named source order per
   field — use it. Specifically:
   - Fees: official site, then Edustoke, then Ezyschooling. If you find an annual amount but no
     class-wise table, that is **Tier 2** - publish the amount and say class-wise figures aren't
     published. Do **not** write "contact the school" when you have a figure.
   - Board / grades / year established / location / medium / co-ed: check CBSE SARAS and the
     UDISE record (via `schools.org.in` school pages, found by web search — its own site search
     is broken). Verify the page's school name *and* locality match before trusting it.
   - Facilities with nothing on record: **omit the table row** rather than filling it with a
     fallback sentence.
   - Reserve "Contact the school for the latest details." for current-cycle admission dates, seat
     vacancies, and fees you genuinely could not find anywhere.
   Record every gap and every source conflict in notes.md and keep going.
5. **Length:** follow the skill's word count formula (about 250-300 words per school plus intro, conclusion and FAQ). Don't go far over it. You have no shell, so don't try to count the words yourself: the pipeline's QC counts them and reports the ratio.
6. **Images and graphs are handled by the pipeline after you finish. Don't download images, don't run any shell commands and don't draw charts.** Instead:
   - In blog.md, put `<!-- IMAGE: <school-slug> -->` on its own line where each school's image goes (after the 3 intro bullets, before the info table), and `<!-- GRAPH: <school-slug> -->` on its own line where each school's parent review graph goes (after the review bullets). `<school-slug>` is the school name lowercased and hyphenated.
   - Don't add a markdown fallback table for the graph. The graph replaces it.
   - Write `{out_dir}/assets.json`:
     `{{"schools": [{{"name": "<school name>", "slug": "<school-slug>", "image_url": "<direct URL of a campus photo on the school's official website, or null>", "reviews": {{"<Category>": [<positive %>, <negative %>], "...": [0, 0]}}}}]}}`
     The review percentages must match the percentages in the blog text exactly. **`reviews` is never null.**
     Every school gets category percentages and a graph, no matter how thin or contradictory the
     review base is — derive them from whatever exists (aggregate rating, a handful of written
     reviews, follower and shortlist counts) and say in the review bullets that the base is small.
     A thin base is a caveat to state, never a reason to omit the percentages or the graph.
7. **Save into the folder `{out_dir}`** (relative to the current directory):
   - `{out_dir}/blog.md`. No H1 title in the file: it starts with the introduction paragraph, as the skill says.
   - `{out_dir}/meta.json` with keys `title`, `meta_title`, `meta_description`, `slug` (use the slug given above; primary keyword in title and meta_title).
   - `{out_dir}/assets.json` as above.
   - `{out_dir}/notes.md`: a short list of missing data, conflicting sources and anything a human should check before publishing.
8. **Only read files in the skill folder and in `{out_dir}`.** Don't open, list or search other folders under `output/` or `data/`: they hold other blogs and old runs, and copying from them mixes up schools.
9. Run the skill's quality checklist yourself before finishing (images and graphs excepted, the pipeline adds them).

When done, reply with one line: DONE or FAILED: <reason>.
