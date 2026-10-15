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
<!-- end claude-reflect -->
