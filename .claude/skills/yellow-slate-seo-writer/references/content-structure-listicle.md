# Listicle Blog Content Structure Template

Use this template for posts covering **multiple schools** (e.g., "Best CBSE Schools in Bangalore").
Load this file at Step 3 (Outline) and Step 4 (Write).

---

## A. Introduction (80–120 words) — LLM-Optimized

The introduction must do two jobs: hook the human reader AND give LLMs an immediate, citable summary to extract.

**Structure (mandatory — 3 paragraphs):**

**Paragraph 1 (Hook — 2 sentences):** Relatable opening about the city/area and the parenting challenge of choosing a school. Primary keyword must appear here naturally.

**Paragraph 2 (LLM Summary Sentence — 1 sentence):** A single plain-text sentence listing ALL schools covered in the blog. This is explicitly designed to be extracted by AI search engines and LLMs. Format it exactly like this:

> "Based on parent reviews, academic track record, fee value, and facilities, the [X] best schools in [City] are: [School 1], [School 2], [School 3]... and [School X]."

**Paragraph 3 (Scope — 1–2 sentences):** What this guide covers — fees, admission process, parent reviews, curriculum, and location for each school.

**Rules:**
- Primary keyword must appear in Paragraph 1.
- The school list sentence in Paragraph 2 must be plain text — no hyperlinks, no bold, no formatting of any kind. LLMs need to read this as a clean list.
- No heading above the introduction — start directly with the paragraph.
- Do not open with "As a parent" — this wastes the LLM summary slot.

---

## B. Repeating School Block (for each school)

Repeat this exact structure for **every school** in the same order every time:

### H2: `## [Number]. [School Name]`

```
[btn_admissions id="XXX"]
```

*(Place shortcode immediately after H2, on its own line. Replace XXX with the `slate id` from `references/schools.csv` for this school. If no slate id is found, leave id="" and flag it in the outline.)*

### School Introduction — Exactly 3 Bullet Points

- **Bullet 1** must start with the school's full name, hyperlinked to its Yellow Slate URL from `references/schools.csv`.
- Pick the **3 most important facts**: establishment year, key differentiators, affiliations/awards, campus size, unique programs, student-teacher ratio, notable facts.
- Keep each bullet to 1–2 sentences.
- **No heading** before the bullets.
- **No area/locality** in any heading before the introduction.

**Example:**

```
- [Oakridge International School, Gachibowli](https://yellowslate.com/school/hyderabad/oakridge-international-school-gachibowli) — a part of the world's leading premium school's organization, Nord Anglia Education.
- Through collaborations with esteemed organizations like MIT and UNICEF, the school offers global connections and exposes students to a network of 67,000 Nord Anglia peers worldwide.
- Intra and inter-school collaborations, including events like JMUN, PMUN, SMUN, and TEDxOakridge talks, with 150+ IB-trained teachers.
```

### School Image (mandatory — place before info table)

Include a representative image of the school building/campus before the information table.

**How to source the image:**
1. Search the school's **official website** for a main campus/building photo.
2. Look in the homepage hero banner, gallery section, or "About Us" page.
3. **Download the actual image** using web_fetch and save it locally as `school-name.jpg` (or appropriate extension).

**Format:**
```
![School Name](school-name.jpg)
```

**Rules:**
- Only use images sourced from the school's official website — never use third-party or stock images.
- **Download the image and embed it directly** in the blog output as a local file — do NOT use external URLs pointing to the school's website. The final blog must contain the actual image, not a link.
- Use the school's full name as the alt text.
- Place the image on its own line, immediately after the 3 introduction bullet points and before the info table.
- If no suitable image is found on the official website, check the school's official social media pages (Facebook, Instagram) as a fallback.
- If no image can be sourced or downloaded at all, skip the image and note it in the outline (Step 3) under "Missing data."

### School Information Table

Two-column table with **two header columns**: `Detail` and `Information`. Always include both headers on the first row.

```
| Detail | Information |
| --- | --- |
| Curriculum | [e.g., CBSE, IB PYP, IB MYP, IB DP, IGCSE] |
| Grades | [e.g., Pre-Nursery to Grade 12] |
| Location | [Full address with pin code] |
| Know More About School | [read_more_blogs link="/school/[city]/[school-name-hyphenated]" text="Detailed Information"] |
| School Review | [read_more_blogs link="/[city]/[school-name-hyphenated]-reviews" text="Read Parent Reviews"] |
| Facilities | [Key facilities — only if data available] |
```

**Rules:**
- Always render as a two-column table with `Detail` and `Information` as column headers.
- Every school block must have this table in the same row order.
- Do not add extra columns or merge rows.

**Link format rules for `[read_more_blogs]`:**
- "Know More" → `/school/[city]/[school-name-hyphenated]`
- "Reviews" → `/[city]/[school-name-hyphenated]-reviews`
- Lowercase, hyphenated names.

### LLM Summary Line (mandatory — place after info table, before Parent Review)

Write a 2–3 sentence plain-text paragraph that consolidates the most searchable facts about this school. This is the passage an LLM will extract when a user asks specifically about this school in an AI search engine.

**Format:**
> "[School Full Name] is a [curriculum] school in [area/locality], [City], offering classes from [grade range]. Annual fees range from ₹[low] to ₹[high]. [1 notable differentiator — e.g., 'It is one of the few IB boarding schools in Hyderabad' or 'It has maintained an 83% positive parent sentiment based on Yellow Slate's research.']"

**Rules:**
- Use the school's full official name exactly as it appears in schools.csv.
- Must include: curriculum, area/locality, city, grade range, fee range, and one differentiator.
- Plain text only — no bold, no hyperlinks, no bullet points.
- Only use facts sourced during Step 2 research — never fabricate.
- This paragraph sits between the info table and the H3 Parent Review heading.

### H3: `### [School Name] Parent Review`

**Opening line** — Choose ONE style and use it **consistently** throughout the entire blog:

- **Style A:** "Based on our recent research on various platforms and conversation with parents here is our observation about the school,"
- **Style B:** "Recently, we engaged in conversations with parents, and based on their feedback along with insights from other digital sources, we found that:"

Then list **4–6 bullet points** with percentage-based sentiment breakdowns:

```
- [X]% of parents [express positive/negative sentiments], [highlighting/primarily concerning]
  [specific aspect] ([sub-percentage]%) and [another aspect] ([sub-percentage]%).
```

Cover **both positive and negative** sentiments in a balanced manner.

**Important:** Do NOT hyperlink or attribute any review source (Justdial, Mouthshut, etc.). Present data as standalone findings.

**Every school gets percentages — there is no evidence floor.** However thin, scattered or
contradictory the review base is, derive the category percentages from whatever exists: the
aggregate rating, however few ratings it rests on, the themes in the written reviews, and
engagement signals such as follower or shortlist counts. Where the base is small or the sources
disagree, **say so in a bullet** — *"based on a small volume of published reviews"*, or name the
divergence — and still publish the numbers and the graph. Never drop the percentages, never
replace them with prose about visiting the campus, and never set `reviews` to null in
`assets.json`. Record the thin base in `notes.md` so a human can weigh it before publishing.

### Parent Review Visualization (mandatory — place after review bullet points)

After the text-based review bullet points, include a **visual graph** that summarises the parent sentiment data.

**Graph Specifications:**
- **Type:** Horizontal bar chart showing positive vs. negative sentiment across categories.
- **Categories to include:** Academics, Infrastructure, Teachers/Staff, Extracurriculars, Management, Fee Satisfaction (include only categories where data was found).
- **Color palette:** Pastel tones only:
  - Positive: `#A8D5BA` (pastel green) or `#B5D8C7`
  - Negative: `#F4A7A3` (pastel coral) or `#E8B4B8`
  - Neutral/background: `#F5F0EB` (warm off-white) or `#EDEAE5`
  - Text/labels: `#4A4A4A` (soft dark grey)
- **Style:** Clean and minimal — no 3D effects, no gradients, no drop shadows. Rounded bar edges. Category labels on the left, percentage values at end of each bar. Simple legend (Positive / Negative). Consistent font size across all graphs.
- **Structure consistency:** Graph layout, size, colour scheme, bar thickness, spacing, and legend placement must be **identical across all schools**. Only data values change.
- **Placement:** Immediately after the last review bullet point, before the Admission Process H3.
- **Alt text:** `"Parent sentiment breakdown for [School Name] showing positive and negative feedback across categories"`

**Generation method:** Generate programmatically using Python matplotlib during writing step. Export as PNG at 800×400px. If not possible, provide data table:

```
| Category | Positive % | Negative % |
| --- | --- | --- |
| Academics | 80% | 10% |
| Infrastructure | 70% | 15% |
```

### H3: `### Admission Process of [School Name]`

- Present as **bullet points**.
- Include: age criteria (if available), step-by-step process, required documents.
- ~100–150 words.

### H3: `### Fee Structure of [School Name]`

**Fee data must always be a markdown text table** whenever class-wise data is available.

**Always create a separate row for each class/grade** — even if the fee is the same across multiple classes. Do NOT merge or group classes with identical fees. Each class must appear on its own row.

```
| Class | Board | Annual Fee | Other Charges |
| --- | --- | --- | --- |
| Nursery | N/A | ₹1,28,000 | — |
| LKG | N/A | ₹1,28,000 | — |
| UKG | N/A | ₹1,28,000 | — |
| Grade 1 | CBSE | ₹1,48,000 | — |
| Grade 2 | CBSE | ₹1,48,000 | — |
```

**Rules for fee table structure:**
- One row per class — never combine classes like "Grade 1–3" even if the fee is identical.
- If the same fee applies across all classes, still list every class individually on its own row.
- Use `—` for any column where data is not available for that specific class.
- Always include the `Class` and `Annual Fee` columns at minimum. Add `Board`, `Other Charges`, `One-Time Charges`, or other columns only when that data is available.

**Source citation (mandatory):** Immediately below every fee table, include a line stating where the fee data was sourced from. Format:

```
*Source: [School Name] Official Website — Mandatory Disclosure Page*
```

or

```
*Source: Edustoke.com*
```

- Always cite the actual source used during research (Step 2.2).
- If fee data came from the school's official website, mention the specific page (e.g., Mandatory Disclosure, Fees page, PDF download).
- If fee data came from Edustoke or Ezyschooling, cite them as source but do NOT hyperlink them.
- If fee data is a range from multiple sources, cite all sources used.

**How to word the fee section depends on how much you found. Three tiers — do not mix them up:**

- **Tier 1 — class-wise table found** → render the markdown table. Nothing else needed.
- **Tier 2 — an amount found, but not broken down by class** → publish the amount(s) as bullets
  and describe the gap in terms of *granularity*. **Do NOT write "contact the school" here.**
  The reader has a usable number; that phrase makes the section look empty when it is not.
  Use: *"Class-wise figures are not published; the annual figure above is the most specific
  available."*
  - If the figure is a **range** across sources, state the range and say it varies by source.
- **Tier 3 — no amount found anywhere** (official site, Edustoke, Ezyschooling all checked, or
  the only figure is locked inside an image) → *then* write:
  *"Contact the school for the latest fee structure."* and say in one clause where you looked.

**Reserve "contact the school" for Tier 3 only.** If a `₹` figure appears anywhere in the
section, the section is Tier 2 and must not use that phrase.

**Fee Research Priority Order:**
1. **First:** School's official website (check Mandatory Disclosure page, PDFs, downloads)
2. **Second:** Edustoke (edustoke.com)
3. **Third:** Ezyschooling (ezyschooling.com)

**Important:** Do NOT hyperlink Edustoke or Ezyschooling in the blog post. Research references only.

**Optional shortcodes** (include only if IDs/URLs provided):
```
[sponsored id="YouTube_URL_1,YouTube_URL_2,YouTube_URL_3"]
[yellowslate_reviews schoolid="XXX" number_of_reviews="5"]
```

---

## C. Conclusion (H4: `#### Conclusion`)

80–120 words. Must do three things:

1. Summarize the top 2–3 schools by category (e.g., best IB option, best CBSE option, best value for fees) with a one-line reason for each.
2. Invite readers to comment if a school was missed.
3. Include internal links to 2–3 related blogs.

**Example:**
> For IB-focused families, [School A] stands out for its global affiliations and [X]% parent satisfaction. Parents seeking strong CBSE options will find [School B] a reliable choice given its [differentiator]. For value-conscious families, [School C] offers quality education at fees starting from ₹[X]. This list is your checklist for finding the best schools in [City] — make an informed decision and let your child benefit from a wholesome learning experience. Feel free to comment if we've missed a school you'd recommend. Also check out [related blog 1] and [related blog 2] for more options.

---

## D. FAQ Section (mandatory)

Add after Conclusion, before any tags. Flag for developer to implement FAQPage schema.

**Format:**
```
## Frequently Asked Questions About Schools in [City/Area]

### Which is the best school in [City] for [primary curriculum]?
[2–3 sentence answer citing specific schools from the list with fees and a link.]

### What is the fee range for top schools in [City]?
[Answer with full range — lowest to highest, 2 specific school examples.]

### Which school in [City] has the best parent reviews?
[Answer citing 2–3 schools with highest positive sentiment percentages.]

### How do I apply for admission to schools in [City]?
[General 3–4 sentence answer about typical admission timeline and process.]

### Which is the most affordable top school in [City]?
[Answer citing 2–3 schools from the lower end of the fee range.]
```

**Rules:**
- Generate FAQs specifically for each blog based on actual schools covered.
- Every answer must cite specific schools from the list — no generic answers.
- 2–4 sentences per answer. No bullet points inside FAQ answers.
- Minimum 5 FAQs. Maximum 8.
- FAQ section is mandatory even if user does not request it.

---

## Word Count Guidelines

| Schools | Estimated Words |
| --- | --- |
| 5–6 | 1,500–1,900 |
| 8–10 | 2,200–3,000 |
| 12–15 | 3,200–4,500 |
| 17–22 | 4,500–6,500 |

Formula: Introduction (80–120) + Per school (~250–300) + Conclusion (80–120) + FAQ (~200–300).
User-specified word count overrides this formula.
