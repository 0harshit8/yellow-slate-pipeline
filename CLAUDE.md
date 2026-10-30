<!-- claude-reflect: learned rules (saved from the band; edit freely) -->
## Learned rules
- Limit all place recommendations and research in this project to India only; exclude destinations outside India.
- Architecture: `clients/` are raw API wrappers, `stages/` are the callers that orchestrate
  them, `pipeline.py` is the CLI. A client docstring saying "the caller has to supply X" is an
  instruction to a stage, not to you.
- Before calling anything missing, blocked or impossible — and before asking the user about it
  — grep `stages/` and `pipeline.py` and read the calling stage end to end. Reading only the
  client produces false blockers. Then say what you read that failed to answer it.
- Never drop a school because its locality was not found. `UnplaceableSchool` in
  `stages/cms.py` is a prompt to go and research the address, not a verdict. The listing page
  a competitor shows is not the only source: the directory's own per-school detail page, the
  UDISE record on `schools.org.in` and CBSE SARAS routinely carry a full postal address when
  the list page carries none. Find the locality and fill the Area column in the Schools tab,
  then rerun. Exclude a school only for a substantive reason, such as being in a different
  city or district, and say which.
- Karnataka district data in old directories predates the Aug 2007 split that created
  Chikkaballapur out of Kolar. Gauribidanur, Gudibanda, Bagepalli, Chikballapur, Sidlaghatta
  and Chintamani are Chikkaballapur taluks now, though postal data still prints "(Kolar)".
  Kolar district proper keeps Kolar, Malur, Bangarpet, Mulbagal, Srinivaspur and KGF.
- Do not ask the user a question the repo already answers. `stages/pick.py` states how schools
  are picked; `stages/selection.py` fixes the count at 8-12 (`MIN_VOL` 100, top up to 8, cap
  12); `stages/cms.py` creates missing schools and resolves their areas. Volumes are the one
  input that must come from the user by hand.
- Ensure generated blog admission, fee, parent review, and graph sections are populated with real data; never output empty or placeholder graphs.
- Never name a third-party site in the published blog. No "Ezyschooling says", "per Careers360",
  "Source: Edustoke.com" -- not in prose, not in a table cell, not in a Source line. State the
  figure as Yellow Slate's own: "The campus has 3,637 students and 118 teachers." The school
  itself, its board (CBSE, ICSE, CISCE) and government registries are not third parties and
  may be named. This applies to the blog only: fact sheets in `data/research/` must keep every
  source URL, because that is the verification trail and the writer needs it to judge a figure.
- The pipeline never looks for or adds school images. The user adds them by hand after the
  blog is written. Researchers must not spend a search, a fetch or a fact-sheet line on a
  photo, the writer leaves no image slot, and a blog with no photo is not a QC finding.
  `stages/draft.py` still uploads any image found in `output/<slug>/images/`, which is the
  manual path.
<!-- end claude-reflect -->
