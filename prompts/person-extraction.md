# Instructions

You are extracting people mentioned in Civil War pension document transcriptions.

For every person mentioned in the text, extract their name details and a brief context.  Provide as many details as available for each person found

Rules:
- Return ALL people mentioned, including clerks, soldiers, widows, witnesses, etc.
- Return people even mentioned in passing such as "Georges Hardware Store"  this should retrun a person with first name George context Owner of Hardware Store and everything else is "--"
- All fields are required. Use "--" for any field that is not present in the text.
- context: a very brief note on where/how this person appears (e.g. "soldier", "widow claimant", "witness", "notary")
- middle_initial: single letter only (no period), or "--"
- prefix: e.g. Mr, Mrs, Dr, Col, Pvt, Capt — or "--" (no period)
- suffix: e.g. Jr, Sr, II — or "--"
- title: civilian/military title if separate from prefix (e.g. "Pension Agent") — or "--"
- reference: The exact sentence where the Person was found.
