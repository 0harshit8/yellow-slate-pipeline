# Yellow Slate API integration: what the blog pipeline needs

The pipeline that writes the 600 "Schools in [Area]" listicles is finished and running against a
stand-in CMS. Two pieces are missing, both of them API clients.

Each piece is **two functions in one file**. Nothing else in the pipeline changes.

| Priority | File to fill in | Functions | Verified by |
|---|---|---|---|
| 1. Schools (blocking) | `cms_api.py` | `search_school`, `create_school` | `verify_cms_api.py` |
| 2. Blog drafts | `blog_api.py` | `create_draft`, `upload_image` | `verify_blog_api.py` |

Part 1 blocks the whole project: no blog can be written until missing schools can be added. Part 2
only affects publishing speed, so it can land later.

Setup for everything here is Python 3.9+ and `pip install requests`. No Google Sheet, no other
credential, nothing from the rest of the pipeline. Both verify scripts run standalone and print the
raw response for every call.

---

# How to work in this

1. Unzip the folder anywhere. Run `pip install requests`.
2. **Two files to edit: `cms_api.py` and `blog_api.py`.** Nothing else. Each has two methods marked
   `TODO`, with example code sitting commented out underneath showing the shape of the answer. Fill
   those in against the real endpoints.
3. **Do not change the function names, their arguments, or the return shapes.** The pipeline calls
   them exactly as they are written. Everything inside the functions is yours to write however the
   API needs; the edges have to stay as they are. Check 0 in each verify script enforces this, so
   you will know immediately if something drifted.
4. **Wrap every failure in `CMSError` / `BlogError`.** Timeouts, non-JSON responses, missing fields,
   all of it. The pipeline retries a failed row later, but only if the error arrives in that shape.
   Check 7 tests this by pointing the client at an address with nothing listening.
4. Set the two environment variables and run the matching verify script. It prints `PASS` or `FAIL`
   per check with the raw response, so it tells you what to fix.
5. Repeat until it passes. That is the finish line, there is nothing else to check.

Working in Claude Code is the quickest way to do it. Open this folder and paste something like:

```
Read README.md in this folder. Then fill in the two TODO methods in cms_api.py against
our schools API. Do not change any function name, argument or return shape. When done,
run verify_cms_api.py and fix whatever fails.
```

Then the same for `blog_api.py` and `verify_blog_api.py`. Paste or point it at the API docs if there
are any; if there are none, the endpoints can be described in chat.

Both verify scripts create real test records (`ZZ Test School <timestamp>`, and a draft on a
`zz-test-...` slug). They are named that way so they are easy to find and delete afterwards.
`verify_cms_api.py --no-create` runs only the read-only checks if you want to start safe.

---

# Part 1: schools API

About 5,000-6,000 schools need to be added across the 600 blogs, in batches of 100-250.

## `search_school(name, city, area)`

Looks up whether a school already exists, so the pipeline never creates a duplicate.

- `name` is a full school name including the area, e.g. `"Delhi Public School Kalkaji"`.
- Matching should be **loose on the name, exact on city + area**. The same school appears in
  different forms across sources: `DPS` vs `Delhi Public School`, `Guru Har Krishan` vs
  `Guru Harkrishan`, `Sri Sathya Sai` vs `Shri Satya Sai`. If the API only does exact matching, say
  so and return the candidate list instead; the pipeline has name-matching logic it can apply on
  its own side.
- Returns, on a hit:
  ```python
  {"id": 23817, "name": "Delhi Public School Kalkaji", "slug": "delhi/delhi-public-school-kalkaji"}
  ```
  - `id` is the **slate ID**, the one that goes in `[btn_admissions id="XXX"]`.
  - `slug` is the **profile URL path**, the same value as `Profile URL` in the schools CSV export.
- Returns `None` when there is no match. Not an empty dict, not an error.
- If two schools in the same city + area match, return the better match. The pipeline flags it for a
  human.

## `create_school(name, city, area, email)`

Creates one school and returns its ID and slug.

- Always set **verified = No** and **claimed = No**.
- Cities and areas already exist in the CMS. This call never creates them, only references them.
- Returns the same shape as a search hit: `{"id", "name", "slug"}`. The `id` must be the real slate
  ID, because the blog body is built from it.
- On failure, raise `CMSError` with the API's message in it. Do not return `None` and do not swallow
  the error; the pipeline marks the row failed and retries it later.

## Rules the pipeline already applies before calling

Settled, listed only so the responses can be checked against them.

- **Name** = school name + area, e.g. `"Bal Bharati Public School Kalkaji"`. Board is added by hand
  only when one school has two campuses in the same area. Full names, no short forms.
- **Email** = the name's letters and digits only, plus `@gmail.com`, e.g.
  `delhipublicschoolkalkaji@gmail.com`.
- **Search always runs before create.** Reruns are safe and must stay safe.

## How to prove it works

```bash
pip install requests
set YS_CMS_BASE_URL=https://.../api        # export on mac/linux
set YS_CMS_API_KEY=...
python verify_cms_api.py --city Delhi --area Kalkaji --known "Delhi Public School Kalkaji"
```

Eight checks, pass/fail on each:

0. The file still matches the contract: `ApiCMS` subclasses `CMS` and both signatures are unchanged
1. A known existing school is found, with an `id` and a `slug`
2. A short form of that same school (`DPS Kalkaji`) is also found, or is reported as a limitation
3. A made-up name returns `None`, not a wrong match and not an error
4. A throwaway test school is created and comes back with an `id` and a `slug`
5. Searching that new school immediately finds it, with the same `id`
6. Creating it a second time is handled, not silently duplicated
7. Failures come back as `CMSError`, checked by pointing the client at a dead address

Two of those matter more than the rest.

**Check 5.** If a school cannot be found right after it is created, a rerun duplicates it, and this
runs about 6,000 times.

**Check 7.** The pipeline processes schools in batches and marks one row failed to retry it later.
It can only do that if the failure arrives as `CMSError`. A raw `requests` timeout or a `KeyError`
escaping the client takes down the rest of the batch with it. So wrap everything, including
timeouts, bad JSON and missing fields.

The test school is named `ZZ Test School <timestamp>` so it is easy to find and delete afterwards.
Pass `--no-create` to run only the read-only checks first.

## Questions for part 1

1. **Do school emails have to be unique?** Different cities have schools with identical names. If
   they must be unique, the plan is `schoolnamearea@gmail.com`, which is what the pipeline generates
   today. Confirm that works.
2. **Rate limit.** Requests per second or per minute to stay under.
3. **Auth.** Header name and format for the key, and whether the key is per user or per app.
4. **Error shapes.** Status code and body for: school already exists, duplicate email, unknown city
   or area, bad key.

---

# Part 2: blog draft API

Not blocking, but it is the difference between publishing 600 blogs through the API and pasting 600
blogs in by hand.

Two calls, used in this order per blog: **every image is uploaded first**, the returned URLs are
substituted into the body, then the draft is created. So `upload_image` has to work for
`create_draft` to be worth anything. Each blog carries roughly 20 images (one photo and one parent
review graph per school, 8-12 schools), so the full run is around 12,000 uploads.

## `upload_image(path, alt="")`

- One local `.jpg` or `.png` at a time.
- Returns `{"url": "https://..."}`. The URL must be **absolute**. A relative path breaks the body.

## `create_draft(blog)`

```python
blog = {
    "title":            "10 Best Schools in Kalkaji, Delhi 2026-27: Fees, Reviews & Admission",
    "meta_title":       "10 Best Schools in Kalkaji, Delhi 2026-27: Fees & Reviews",
    "meta_description": "Compare the 10 best schools in Kalkaji, Delhi for 2026-27 ...",
    "slug":             "best-schools-in-kalkaji-delhi",
    "city":             "Delhi",
    "area":             "Kalkaji",
    "content":          "<the blog body>",
}
```

Returns `{"id", "slug", "status", "edit_url"}`.

Four things that matter:

- **It must create a draft, never publish.** Every blog gets reviewed before going live. `status`
  has to come back unpublished.
- **The slug must be kept exactly as sent.** The blog URL pattern is
  `best-schools-in-<area>-<city>`, and it is set upstream. The CMS regenerating its own slug breaks
  internal linking across the 600 blogs.
- **Idempotent on slug.** A slug that already exists returns that draft, never a second one. Failed
  rows get retried, so this will happen.
- **`edit_url`** so the draft can be opened for review without hunting through the admin for it.

### What the body actually contains

The body is not plain prose. A real section looks like this:

```markdown
## 1. Deepalaya School Kalkaji

[btn_admissions id="900001"]

- [Deepalaya School Kalkaji](https://yellowslate.com/delhi/deepalaya-school-kalkaji-kalkaji) is a CBSE school.
- Second intro bullet.
- Third intro bullet.

| Detail | Information |
| --- | --- |
| Curriculum | CBSE |
| Know More About School | [read_more_blogs link="/school/delhi/deepalaya-school-kalkaji-kalkaji" text="Detailed Information"] |

![Parent sentiment breakdown for Deepalaya School Kalkaji](https://.../deepalaya-school-kalkaji.png)
```

So it has to survive, unescaped and unmangled: the `[btn_admissions]` and `[read_more_blogs]`
shortcodes, markdown tables, markdown links and images, rupee amounts, and apostrophes.

There is **no H1 in the body**. The title is a separate field.

## How to prove it works

```bash
set YS_BLOG_BASE_URL=https://.../api       # export on mac/linux
set YS_BLOG_API_KEY=...
python verify_blog_api.py --city Delhi --area Kalkaji
```

Eight checks:

0. The file still matches the contract: `ApiBlog` subclasses `Blog` and both signatures are unchanged
1. An image uploads and comes back with an absolute URL
2. That URL actually serves an image, not a 404 or an HTML page
3. A draft is created and returns `id`, `slug`, `status`, `edit_url`
4. The slug is kept exactly as sent
5. The draft comes back unpublished
6. Re-sending the same slug returns the same draft instead of duplicating
7. Failures come back as `BlogError`, checked by pointing the client at a dead address

The script generates its own test image, so no files are needed. It creates a draft on the slug
`zz-test-best-schools-in-<area>-<city>`, which is safe to delete.

At the end it prints an eye-check list for the draft it created: open the `edit_url` and confirm the
shortcodes, the table, the image and the rupee amounts all came through intact. A script cannot
judge that, and it is the thing most likely to be quietly wrong.

## Questions for part 2

5. **Content format: HTML or markdown?** The pipeline produces markdown today and can convert to
   HTML. Whichever the API wants is fine, it just has to be stated, because the shortcodes and
   tables have to survive the conversion.
6. **Do the shortcodes work through the API as they do in the editor?** `[btn_admissions id="123"]`
   and `[read_more_blogs link="..." text="..."]`, unescaped.
7. **Images:** max file size, allowed types, and is the returned URL absolute?
8. **Can a draft be re-sent to update it**, or does a second call duplicate?
9. **Author and category.** Does a draft need an author ID, or a category or city reference set, and
   what should it be?
10. **Same key as the schools API, or a separate one?**

---

# What to send back

- The filled `cms_api.py`, with `verify_cms_api.py` output
- The filled `blog_api.py`, with `verify_blog_api.py` output
- The API key or keys, and the base URLs
- Answers to the ten questions above

With those, the pipeline switches from the stand-in CMS to the real one by changing two lines of
config: `CMS_MODE=api` and `BLOG_MODE=api`.
