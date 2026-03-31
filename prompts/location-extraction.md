# Instructions

You are extracting locations mentioned in Civil War pension document transcriptions.

For every location mentioned in the text, extract its details and a brief context. Provide as many details as available for each location found.

Rules:
- Return ALL locations mentioned, including cities, counties, states, countries, plantations, military posts, battlefields, churches, cemeteries, streets, and regions.
- Return locations even mentioned in passing (e.g. "near Charleston" should return a location with place_name "Charleston").
- All fields are required. Use "--" for any field that is not present in the text.
- place_name: the name of the location exactly as written in the document
- type: classify the location — use one of: city, town, village, county, state, territory, country, plantation, military_post, battlefield, church, cemetery, street, neighborhood, region, other
- city: city or town name, or "--"
- county: county name, or "--"
- state: full state or territory name, or "--"
- country: country name, or "--"
- context: a very brief note on how this location appears (e.g. "soldier's birthplace", "location of deposition", "plantation where soldier was enslaved", "regiment's station")
- reference: the exact sentence where the location was found
