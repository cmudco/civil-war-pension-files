# Civil War Pension Files — Student Team Overview

## Project Background

This project is digitizing and analyzing Civil War pension files from the National Archives (USCT — United States Colored Troops). These files contain scanned images of handwritten and typed pension documents filed by soldiers, their widows, and witnesses in the decades following the Civil War.

Each pension file belongs to one soldier and can contain dozens to hundreds of pages — affidavits, certificates, correspondence, medical examinations, and administrative records. A single file may reference many different people: the claimant, their family members, witnesses, doctors, pension agents, and clerks.

---

## What You Have Been Given

### 1. PDF Files
The dataset has expanded from the original 7 files to **20 pension files** totaling **2,330 pages**:

| File | Pages |
|---|---|
| Abbs Wilkins.pdf | 77 |
| Barnwell Paul Civil War Pension.pdf | 79 |
| Brown (John) Mustifer Civil War Pension.pdf | 191 |
| Brown Adam Civil War Pension.pdf | 37 |
| Brown Frederick Civil War Pension.pdf | 70 |
| Brown George.pdf | 11 |
| Brown Harry Civil War Pension.pdf | 220 |
| Brown Isaiah Civil War Pension.pdf | 174 |
| Cuthbert Sampson Civil War Pension.pdf | 131 |
| Dulaney Jacob (Jones) Civil War Pension.pdf | 75 |
| Fields Daniel Civil War Pension.pdf | 70 |
| Fripp Alfred Civil War Pension.pdf | 182 |
| Goodwin Robert Civil War Pension.pdf | 354 |
| Green Moses Civil War Pension.pdf | 113 |
| Jenkins July Civil War Pension.pdf | 137 |
| Jones Jacob Civil War Pension.pdf | 66 |
| Jones William Civil War Pension.pdf | 95 |
| Legare Murray Civil War Pension.pdf | 62 |
| Legaree Benjamin (aka Williams Ben) Civil War Pension.pdf | 160 |
| Robinson, Lucius.pdf | 26 |

### 2. Page Images (`/images`)
Every page of every PDF has been converted to a JPEG image at 200 DPI. Files are named `{SoldierName}_page{N}.jpg`. These are the actual images sent to the AI for transcription and can be used to verify transcription accuracy or inspect the original document.

### 3. Transcription Files (`/transcriptions`)
Each page of each PDF has been transcribed to a plain text file using Google Gemini AI. The transcriptions are 1:1 representations of the original document text, including handwritten content. Files are named `{SoldierName}_page{N}.txt`.

### 4. Database (`transcriber_db.db`)
A SQLite database containing all structured data. See schema below.

---

## How This Dataset Was Built

### Step 1 — Source Material
The pension files were sourced from the **International African American Museum (IAAM)** website, which has digitized and made publicly available a collection of USCT pension files from the National Archives. The files are scanned PDFs — each page is an image of an original handwritten or typed document, not machine-readable text.

### Step 2 — Starting File Selection
We began with **Abbs Wilkins** as our first file. This was a reasonably sized, fairly representative record chosen as a starting point to test the pipeline. Each page of the PDF was converted to a high-quality JPEG and sent to Google Gemini for transcription.

The result of this step is a plain text file for each page, stored in the `/transcriptions` folder and logged in the `transcriptions` table of the database.

### Step 3 — Person Extraction
Once the transcriptions existed, we ran a second AI pass using **OpenAI GPT-4o-mini** with structured outputs. For each page, the model was asked to identify every person mentioned — no matter how briefly — and return structured records containing their name components (first, last, middle, prefix, suffix, title), a brief context of who they are in the document, and the exact sentence where they were found.

This produced the `persons` table — 2,914 person records across 7 files. The extraction captures not just the main claimant but everyone referenced: family members, witnesses, doctors, lawyers, pension clerks, and military officers.

### Step 4 — Cross-File Name Matching (Initial Pass)
After processing Abbs Wilkins, we compared the names extracted from that file against the names of other pension PDF files in our collection. The filenames themselves follow a `FirstName LastName` or `LastName FirstName` convention, so a name match between an extracted person and a filename is a strong signal that the person appears in another soldier's file.

This initial scan identified **Moses Green** as a name appearing in the Abbs Wilkins file that matched the filename `Green Moses Civil War Pension.pdf`. We transcribed and extracted that file next.

Then we extracted names from the **Moses Green** file and did a rudimentary search for these names in the files and got a list of 5 additional PDFs:

| Person found in existing files | Matched PDF |
|---|---|
| Paul Barnwell | Barnwell Paul Civil War Pension.pdf |
| Frederick Brown | Brown Frederick Civil War Pension.pdf |
| Isaiah Brown | Brown Isaiah Civil War Pension.pdf |
| Jacob Jones | Jones Jacob Civil War Pension.pdf |
| Benjamin Williams | Legaree Benjamin (aka Williams Ben) Civil War Pension.pdf |

These 5 files were then transcribed and extracted, completing the 7-file dataset.

### Why This Matters
The fact that names from one pension file match the filenames of other pension files strongly suggests these individuals are connected — they may have served in the same regiment, lived in the same community, or appeared as witnesses in each other's claims. The student team's task is to go deeper: systematically identify which person records across all 7 files refer to the same real individual, including cases where the name match is not exact.  This process will then be tested and potentiallty adapted for use at scale.

---

## Database Schema

In addition to persons, the database now includes extracted **locations** and **dates** from every page. Each data type has its own runs table (one row per page processed) and a records table (one row per item found).

### `transcriptions`
One row per transcribed page.

| Column | Description |
|---|---|
| `id` | Primary key |
| `created_at` | When it was transcribed |
| `pdf_file` | Path to source PDF |
| `page` | Page number (1-based) |
| `prompt_name` | Name of the AI prompt used |
| `prompt_text` | The full AI prompt sent to Gemini for transcription |
| `model` | Gemini model used |
| `elapsed_seconds` | How long the transcription took |
| `input_tokens` / `output_tokens` | Token usage |
| `cost_usd` | Cost of this call |
| `txt_file` | Path to exported .txt file |
| `result` | Full transcribed text |

### `extraction_runs`
One row per page that was processed for person extraction.

| Column | Description |
|---|---|
| `id` | Primary key |
| `created_at` | When the transcription was created |
| `transcription_id` | Links to `transcriptions.id` |
| `pdf_file` | Source PDF |
| `page` | Page number |
| `model` | OpenAI model used |
| `input_tokens` / `output_tokens` | Token usage |
| `cost_usd` | Cost of this call |
| `persons_found` | Number of persons extracted from this page |

### `persons`
One row per person mentioned on a page. **This is the primary table for your work.**

| Column | Description |
|---|---|
| `id` | Primary key |
| `extraction_run_id` | Links to `extraction_runs.id` |
| `transcription_id` | Links to `transcriptions.id` |
| `pdf_file` | Source PDF the person was found in |
| `page` | Page number they appear on |
| `first_name` | First name (`--` if not found) |
| `last_name` | Last name (`--` if not found) |
| `middle_name` | Full middle name (`--` if not found) |
| `middle_initial` | Middle initial only, no period (`--` if not found) |
| `prefix` | e.g. Mr, Mrs, Dr, Col, Pvt, Capt — no periods (`--` if not found) |
| `suffix` | e.g. Jr, Sr, II (`--` if not found) |
| `title` | Civilian or military title, e.g. "Pension Agent" (`--` if not found) |
| `context` | Brief description of who this person is in the document |
| `reference` | The exact sentence from the document where this person appears |

**Total persons extracted: 8,949 across 20 files.**

> **Tip:** The `transcriptions` table contains the full transcribed text for every page in the `result` column. If you want to read the original document text for a given person record, join `persons` to `transcriptions` via `transcription_id`.

---

### `location_extraction_runs` / `locations`

One row in `location_extraction_runs` per page processed. One row in `locations` per location found. **6,489 locations extracted across 20 files.**

| Column | Description |
|---|---|
| `place_name` | The location name as written in the document |
| `type` | Classification: city, town, village, county, state, territory, country, plantation, military_post, battlefield, church, cemetery, street, neighborhood, region, other |
| `city` | City or town name, or `--` |
| `county` | County name, or `--` |
| `state` | State or territory name, or `--` |
| `country` | Country name, or `--` |
| `context` | Brief note on how this location appears (e.g. "soldier's birthplace", "plantation where soldier was enslaved") |
| `reference` | The exact sentence where the location was found |

---

### `date_extraction_runs` / `dates`

One row in `date_extraction_runs` per page processed. One row in `dates` per date found. **7,655 dates extracted across 20 files.**

| Column | Description |
|---|---|
| `month` | Month as a number 1–12, or `--` |
| `day` | Day of month as a number, or `--` |
| `year` | Four-digit year, or `--` |
| `date_type` | Classification: birth, death, enlistment, muster_in, muster_out, discharge, marriage, pension_filed, examination, deposition, wound, capture, event, document_date, other |
| `context` | Brief note on what this date refers to (e.g. "soldier's date of birth", "date of pension examination") |
| `reference` | The exact sentence where the date was found |

---

## Weaviate Vector Database

In addition to the SQLite database, all transcribed pages have been embedded and uploaded to a **Weaviate** vector database. This allows you to do semantic similarity search across the full text of all 729 pages.

### Connection Details

| | |
|---|---|
| HTTP host | `weaviate.hss.cmu.edu` |
| gRPC host | `grpc-weaviate.hss.cmu.edu` |
| Port (both) | `443` (secure) |
| Collection | `CivilWarPensionPage` |
| Access | **Read-only** |

> **You must be on the CMU network to connect.** Either be physically on campus or connect via the CMU VPN before running any Weaviate queries.
> VPN instructions: https://www.cmu.edu/computing/services/endpoint/network-access/vpn/

### API Keys

Your Weaviate API key is in the shared Google Drive folder. Navigate to the `weaviate_keys` folder — inside is a Google Doc with links to individual docs containing each team member's key. Use your key as the `WEAVIATE_KEY` value in your `.env` file.

### How the Data is Structured

Each object in the `CivilWarPensionPage` collection represents one chunk of a transcribed page. Most pages are stored as a single chunk. Pages longer than 5,000 characters are split by greedily packing paragraphs (`\n\n` boundaries) until the next paragraph would push the chunk over 5,000 characters — at which point that paragraph starts a new chunk. Chunks overlap by ~400 characters so context is preserved at boundaries.

| Property | Type | Description |
|---|---|---|
| `text` | text | The chunk content |
| `transcription_id` | int | Links back to `transcriptions.id` in the SQLite DB |
| `pdf_file` | text | Full path to the source PDF |
| `pdf_stem` | text | Filename without extension (e.g. `Barnwell Paul Civil War Pension`) |
| `page` | int | Page number within the PDF |
| `chunk_index` | int | 0-based index of this chunk within the page |
| `total_chunks` | int | Total number of chunks for this page |

### Connecting in Python

```python
import os
import weaviate
from weaviate.auth import AuthApiKey
from dotenv import load_dotenv

load_dotenv()

client = weaviate.connect_to_custom(
    http_host="weaviate.hss.cmu.edu",
    http_port=443,
    http_secure=True,
    grpc_host="grpc-weaviate.hss.cmu.edu",
    grpc_port=443,
    grpc_secure=True,
    auth_credentials=AuthApiKey(os.getenv("WEAVIATE_KEY")),
)

collection = client.collections.get("CivilWarPensionPage")

# Semantic search example
results = collection.query.near_text(query="medical examination", limit=5)
for obj in results.objects:
    p = obj.properties
    print(f"{p['pdf_stem']}  page {p['page']}: {p['text'][:200]}")

client.close()
```

---

## Your Task

The core challenge is **entity resolution**: determining which person records across the dataset refer to the same real individual.

This is harder than it sounds because:
- Names are spelled inconsistently across documents (e.g. `Wilkins Abbs`, `Wilkin Abbs`, `Milkins Abbs`, `Hickins Abbs`)
- The same person may appear as a full name on one page and initials only on another (e.g. `J.H. Johnson` vs `John H. Johnson`)
- Nicknames and aliases are common (e.g. `Legaree Benjamin aka Williams Ben`)
- Clerks and pension agents appear across multiple unrelated files
- OCR/transcription errors exist in the underlying text

### Questions to explore:
1. Which person records within a single file refer to the same individual?
2. Which person records **across different files** refer to the same individual?
3. Can you identify pension agents, clerks, or doctors who appear across multiple soldiers' files?
4. What approach (rule-based, fuzzy matching, embeddings, LLM) works best for this problem at scale?

### Getting started with the database

You can open `transcriber_db.db` with any SQLite browser (e.g. [DB Browser for SQLite](https://sqlitebrowser.org/)) or query it in Python:

```python
import sqlite3
import pandas as pd

con = sqlite3.connect("transcriber_db.db")

# Load all persons into a dataframe
df = pd.read_sql("SELECT * FROM persons", con)
print(df.head())

# Find all persons in a specific file
df_file = pd.read_sql("""
    SELECT * FROM persons
    WHERE pdf_file LIKE '%Green Moses%'
    ORDER BY page
""", con)

# Find persons appearing in multiple files
df_multi = pd.read_sql("""
    SELECT first_name, last_name, COUNT(DISTINCT pdf_file) as files
    FROM persons
    WHERE first_name != '--' AND last_name != '--'
    GROUP BY first_name, last_name
    HAVING files > 1
    ORDER BY files DESC
""", con)
```

---

## Notes on Data Quality

- The AI was instructed to use `--` for any field not present in the document — do not treat `--` as a name
- Some pages returned empty transcriptions (blank/illegible pages) — these will have empty `result` fields
- Person extraction was done with GPT-4o-mini; results are good but not perfect — verify against the `reference` field and original transcription text when in doubt, note the extraction process is not what we are testing here, but rather how can we process extraction results across a dataset.
- The `context` and `reference` fields are the most useful for understanding who a person is and validating matches
