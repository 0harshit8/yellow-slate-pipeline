You are extracting school lists from competitor blog pages. Do not use any tools. Answer only with JSON.

The keyword is: "{keyword}"

Below are pages that rank on Google for this keyword. For each page, list the schools the page recommends or ranks as part of its list, and the locality each school sits in.

Rules:
- Only schools that are part of the page's list. Ignore schools mentioned in ads, sidebars, "related posts", navigation, or comments.
- Only K-12 schools (primary, secondary, senior secondary, international). Leave out play schools, preschools, creches, daycares, nursery-only schools, coaching centres and colleges.
- Write each school's name as the page writes it, without numbering.
- If a page has no school list (e.g. a directory search page or an unrelated page), return an empty list for it.
- Do not invent schools. Do not add schools you know of that the page does not list.

The locality rule matters as much as the name, so read it carefully:
- "area" is the neighbourhood or sector the school is in, as the page states it: "Gomti Nagar",
  "Hazratganj", "Sector 62", "Dwarka". Take it from the school's address, the heading, or the
  text around it on that page.
- Write the locality only. No house number, no street, no pin code, no city, no state.
  "Vibhuti Khand, Gomti Nagar, Lucknow 226010" becomes "Gomti Nagar".
- Use the city name as the area ONLY if the page gives a city but no locality at all and you
  cannot tell which part of the city it is in.
- If the page gives no address and no locality for a school, use an empty string. An empty
  string is correct and useful. A guess is not: a wrong locality files the school in the wrong
  place, which is worse than leaving it blank.
- Do not copy the locality from the keyword. A list for one area often includes schools just
  outside it, and those belong under their own locality.

Answer with exactly this JSON shape and nothing else:

{{"pages": [{{"url": "<page url>", "schools": [{{"name": "<name>", "area": "<locality or empty string>"}}]}}]}}

PAGES:

{pages}
