Use the yellow-slate-seo-writer skill to write one blog. This is a batch run with no human in the loop, so follow these overrides to the skill:

1. **Requirements are already gathered (Step 1).** Don't ask for anything.
   - Primary keyword: {keyword}
   - Blog type: Listicle
   - City: {city}
   - Area: {area}
   - Schools, in this order:
{schools}
2. **School URLs and IDs are given above (Step 2.5).** Use them exactly. Don't look schools up in schools.csv and don't ask which branch. The admissions shortcode for each school is `[btn_admissions id="<CMS ID>"]` and the first bullet links the school name to its profile URL.
3. **Outline approval is pre-granted (Step 3).** Don't stop to present the outline. Go straight to writing.
4. If data for a school is missing, follow the skill's rule ("Contact the school for the latest details.") and keep going. Never invent data.
5. **Save everything into the folder `{out_dir}`** (relative to the current directory):
   - the blog as `{out_dir}/blog.md`
   - school images as `{out_dir}/images/<school-slug>.jpg` (download with `curl -L -o`), referenced in blog.md as `images/<school-slug>.jpg`
   - parent review graphs as `{out_dir}/graphs/<school-slug>.png` (matplotlib), referenced as `graphs/<school-slug>.png`
   - a short `{out_dir}/notes.md` listing missing data, missing images and anything a human should check
6. Run the skill's quality checklist yourself before finishing.

When done, reply with one line: DONE or FAILED: <reason>.
