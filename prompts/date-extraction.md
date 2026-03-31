# Instructions

You are extracting dates mentioned in Civil War pension document transcriptions.

For every date mentioned in the text, extract its details and a brief context. Provide as many details as available for each date found.

Rules:
- Return ALL dates mentioned, whether fully specified (month/day/year) or partial (year only, month and year, etc.).
- Return dates even mentioned in passing (e.g. "in the spring of 1863" should return a date with year 1863).
- All fields are required. Use "--" for any field that is not present in the text.
- month: month as a number 1-12, or "--"
- day: day of month as a number, or "--"
- year: four-digit year, or "--"
- date_type: classify what this date refers to — use one of: birth, death, enlistment, muster_in, muster_out, discharge, marriage, pension_filed, examination, deposition, wound, capture, event, document_date, other
- context: a very brief note on what this date refers to (e.g. "soldier's date of birth", "date of pension examination", "date of marriage to claimant")
- reference: the exact sentence where the date was found
