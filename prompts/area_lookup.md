You are finding which locality one school sits in. Do not use any tools. Answer only with JSON.

School: "{school}"
City: {city}

Below are web search results about this school. Read the addresses in them and work out the
school's locality: the neighbourhood, colony or sector, as an address would write it.

Rules:
- Answer with the locality only. No house number, no street, no city, no state, no pin code.
  "Vibhuti Khand, Gomti Nagar, Lucknow 226010" is the locality "Gomti Nagar".
- The locality must be a part of {city}. If the results are about a campus in another city,
  that is the wrong school: answer with an empty string.
- Check the school name matches. These lists often return a similarly named school somewhere
  else. If you are not confident the results are about "{school}" in {city}, answer with an
  empty string.
- Never answer with the city name itself. If all you can tell is the city, answer with an
  empty string.
- An empty string is a correct and useful answer. A guess is not: a wrong locality files the
  school in the wrong place in a live CMS.

Answer with exactly this JSON shape and nothing else:

{{"area": "<locality or empty string>"}}

SEARCH RESULTS:

{results}
