You are extracting school lists from competitor blog pages. Do not use any tools. Answer only with JSON.

The keyword is: "{keyword}"

Below are pages that rank on Google for this keyword. For each page, list the schools the page recommends or ranks as part of its list, and the locality each school sits in.

Rules:
- Only schools that are part of the page's list. Ignore schools mentioned in ads, sidebars, "related posts", navigation, or comments.
- Only K-12 schools (primary, secondary, senior secondary, international). Leave out play schools, preschools, creches, daycares, nursery-only schools, coaching centres and colleges.
- Write each school's name as the page writes it, without numbering.
- A directory's city listing DOES count as a list when it names schools and the town or
  locality of each (careers360's "Schools in <city>" page is the usual one). These are often
  the only pages that give a locality at all, which is the one field a school cannot be filed
  without, so read them as carefully as a ranked listicle.
- Return an empty list only for a page that names no schools: an empty search form, a single
  school's own website, a consultancy's marketing page, or an unrelated page.
- A page that offers schools "in and near <city>" is listing other cities too. Take only the
  ones the page places in this city, and read any distance it prints: "111 km from <city>"
  means the school is not in it.
- Do not invent schools. Do not add schools you know of that the page does not list.
- If the page prints a parent rating next to a school, record how many ratings or reviews it
  rests on as "reviews" (the number, not the stars): "4.0 / 42 Ratings" is 42. Use 0 when the
  page shows no rating, and 0 when it shows stars but no count. Never estimate it. This is how
  a school parents have actually reviewed gets ranked above one that only appears in
  listicles, so take it from every page that prints it, directory listings above all.

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

{{"pages": [{{"url": "<page url>", "schools": [{{"name": "<name>", "area": "<locality or empty string>", "reviews": <how many ratings the page shows, else 0>}}]}}]}}

PAGES:

{pages}
