You are extracting school lists from competitor blog pages. Do not use any tools. Answer only with JSON.

The keyword is: "{keyword}"

Below are pages that rank on Google for this keyword. For each page, list the names of the schools the page recommends or ranks as part of its list for this area.

Rules:
- Only schools that are part of the page's list. Ignore schools mentioned in ads, sidebars, "related posts", navigation, or comments.
- Only K-12 schools (primary, secondary, senior secondary, international). Leave out play schools, preschools, creches, daycares, nursery-only schools, coaching centres and colleges.
- Write each school's name as the page writes it, without numbering.
- If a page has no school list (e.g. a directory search page or an unrelated page), return an empty list for it.
- Do not invent schools. Do not add schools you know of that the page does not list.

Answer with exactly this JSON shape and nothing else:

{{"pages": [{{"url": "<page url>", "schools": ["<name>", "..."]}}]}}

PAGES:

{pages}
