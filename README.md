# Civil War Pension Files

Digitization and analysis pipeline for USCT (United States Colored Troops) Civil War pension files sourced from the [International African American Museum (IAAM)](https://iaamuseum.org/) digital archives. Converts scanned PDF pension files into transcribed text, structured data, and narrative stories using AI.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Transcription | Google Gemini (`gemini-3.1-pro-preview`) |
| Embeddings | Google Gemini (`gemini-embedding-001`) |
| Vector DB | Weaviate |
| Extraction (persons, dates, locations) | OpenAI (`gpt-4o-mini`) |
| Story generation | Gemini + OpenAI (`gpt-5.4`) + Anthropic (`claude-opus-4-6`) |
| Storage | SQLite (`transcriber_db.db`) |
| File storage | AWS S3 + CloudFront CDN |
| PDF rendering | `pdf2image` + Poppler |

---

## Setup

**1. Create and activate a virtual environment**
```bash
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # Mac/Linux
```

**2. Install dependencies**
```bash
pip install -r requirements.txt
```

**3. Install Poppler** (required for PDF-to-image conversion)
- Windows: download from [poppler releases](https://github.com/oschwartz10612/poppler-windows/releases), extract, and set `POPPLER_PATH` in your `.env`
- Mac: `brew install poppler`

**4. Create a `.env` file**
```
GEMINI_API_KEY=
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
WEAVIATE_URL=
WEAVIATE_GRPC_URL=
WEAVIATE_KEY=
POPPLER_PATH=          # Windows only — path to poppler/bin

# AWS S3 + CloudFront
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_REGION=us-east-1
S3_BUCKET_NAME=
CLOUDFRONT_BASE_URL=   # e.g. https://d1abc123xyz.cloudfront.net
```

See `.env.example` for a full template.

---

## Pension Files

The actual PDF pension files are **not included in this repository** — they are gitignored because there are too many and several are too large to track in git. You will need to obtain them separately and place them in the following folder structure:

```
usct_pension_files/
├── A_B/
├── C_D/
├── G_H/
├── M_N/
├── S_T/
└── ...
```

Subfolders are named by the first letters of the soldiers' last names. Place each PDF in the appropriate subfolder.

---

## Pipeline

```
PDFs
 |
 | 01_transcriber.py
 v
S3 (images + transcriptions)  +  transcriber_db.db  (transcriptions table with S3 URLs)
 |
 | 02_transcriber_ingest.py
 v
Weaviate vector DB  (CivilWarPensionPage collection)
 |
 | 03_transcriber_extraction.py           -- persons
 | 03_transcriber_extraction_dates.py     -- dates
 | 03_transcriber_extraction_locations.py -- locations
 v
transcriber_db.db  (persons, dates, locations tables)
 |
 | 04_name_matcher.py
 v
Console report — ranked list of unprocessed PDFs whose soldiers
appear in already-extracted person records, used to select next batch
 |
 | 99_story_teller.py
 v
S3 (stories/{SoldierName}/gemini.md, openai.md, anthropic.md)
+ transcriber_db.db  (stories table with S3 URLs)
```

### Script reference

| Script | What it does |
|---|---|
| `01_transcriber.py` | Converts PDF pages to JPEG, uploads images and transcription text directly to S3, logs CloudFront URLs to DB. **To add new files**, update the `files` list at the bottom of the script — each entry is a tuple of `(relative_pdf_path, pages_or_None)`, where `None` processes all pages. Example: `("usct_pension_files/A_B/Smith John.pdf", None)` |
| `02_transcriber_ingest.py` | Embeds transcriptions and ingests chunks into Weaviate |
| `03_transcriber_extraction.py` | Extracts structured person records from transcriptions via OpenAI |
| `03_transcriber_extraction_dates.py` | Extracts structured date records |
| `03_transcriber_extraction_locations.py` | Extracts structured location records |
| `04_name_matcher.py` | Matches extracted person names against unprocessed PDF filenames to find next targets |
| `99_story_teller.py` | Generates a full narrative story report for every transcribed file using all three AI providers, uploads each to S3, and logs to the `stories` table. Note this costs $.01-$.75+ per file so please be careful running this. A `DEFAULT_BATCH_LIMIT` of 3 is set by default. |
| `99_migrate_to_s3.py` | One-off migration script that uploads existing local images, transcriptions, and stories to S3 and records CloudFront URLs in the DB. Supports `--dry-run` and `--limit N`. Safe to re-run (idempotent). |

---

## Exploration Scripts & Outputs

The `exploration_scripts/` and `outputs/` folders contain one-off test scripts and scrapers used during early development to download, explore, and export data. They are **not part of the main pipeline** and can be safely ignored.

| File | Notes |
|---|---|
| `scraper.py` | Scraped pension file metadata from external sources |
| `test_nara_api.py` | Tested the NARA API |
| `explore.py` | Ad-hoc data exploration |
| `analyze_file.py` | One-off file analysis |
| `export_to_excel.py` | Exported DB data to Excel |
| `extract_service_data.py` | Experimental service record extraction |
| `generate_images.py` | Image generation tests |
| `pension_file_fields.py` | Field mapping experiments |
| `reset_extractions.py` | Utility to wipe and redo extraction runs |
| `weaviate_sample.py` | Weaviate query samples |
| `STUDENT_TEAM_README.md` | Notes for a student team working with the data |

`outputs/` contains any files generated by the above scripts (Excel exports, sample images, etc.).

---

## Database Schema — `transcriber_db.db`

### `transcriptions`
One row per transcribed page.

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER | Primary key |
| `created_at` | TEXT | Timestamp |
| `pdf_file` | TEXT | Source PDF path |
| `page` | INTEGER | Page number (1-based) |
| `prompt_name` | TEXT | Prompt file used |
| `prompt_text` | TEXT | Full prompt sent to Gemini |
| `model` | TEXT | Gemini model used |
| `elapsed_seconds` | REAL | Call duration |
| `input_tokens` | INTEGER | |
| `output_tokens` | INTEGER | |
| `cost_usd` | REAL | |
| `txt_file` | TEXT | Legacy local path (no longer populated) |
| `result` | TEXT | Full transcribed text |
| `s3_image_key` | TEXT | S3 object key for the page image |
| `s3_image_url` | TEXT | CloudFront URL for the page image |
| `s3_txt_key` | TEXT | S3 object key for the transcription text |
| `s3_txt_url` | TEXT | CloudFront URL for the transcription text |
| `zooniverse_subject_id` | TEXT | Zooniverse subject ID once uploaded |
| `verified_transcription` | TEXT | Human-verified transcription from Zooniverse |
| `verified_at` | TEXT | Timestamp of verification |

### `stories`
One row per generated story (three per soldier — one per AI model).

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER | Primary key |
| `created_at` | TEXT | Timestamp |
| `pdf_stem` | TEXT | Soldier name stem (e.g. `Abrams_Henry`) |
| `model` | TEXT | `gemini`, `openai`, or `anthropic` |
| `s3_key` | TEXT | S3 object key |
| `s3_url` | TEXT | CloudFront URL |
| `content` | TEXT | Full story markdown |

### `extraction_runs`
One row per page processed for person extraction.

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER | Primary key |
| `created_at` | TEXT | Timestamp |
| `transcription_id` | INTEGER | FK → `transcriptions.id` |
| `pdf_file` | TEXT | |
| `page` | INTEGER | |
| `model` | TEXT | OpenAI model used |
| `input_tokens` | INTEGER | |
| `output_tokens` | INTEGER | |
| `cost_usd` | REAL | |
| `persons_found` | INTEGER | |

### `persons`
One row per person mentioned on a page.

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER | Primary key |
| `extraction_run_id` | INTEGER | FK → `extraction_runs.id` |
| `transcription_id` | INTEGER | FK → `transcriptions.id` |
| `pdf_file` | TEXT | |
| `page` | INTEGER | |
| `first_name` | TEXT | `--` if not found |
| `last_name` | TEXT | `--` if not found |
| `middle_name` | TEXT | `--` if not found |
| `middle_initial` | TEXT | `--` if not found |
| `prefix` | TEXT | e.g. Mr, Dr, Col — `--` if not found |
| `suffix` | TEXT | e.g. Jr, Sr — `--` if not found |
| `title` | TEXT | e.g. Pension Agent — `--` if not found |
| `context` | TEXT | Who this person is in the document |
| `reference` | TEXT | Exact sentence where they appear |

### `date_extraction_runs` / `dates`
One row in `date_extraction_runs` per page. One row in `dates` per date found.

| Column | Type | Description |
|---|---|---|
| `month` | TEXT | 1–12 or `--` |
| `day` | TEXT | Day of month or `--` |
| `year` | TEXT | Four-digit year or `--` |
| `date_type` | TEXT | birth, death, enlistment, marriage, pension_filed, examination, discharge, etc. |
| `context` | TEXT | What this date refers to |
| `reference` | TEXT | Exact sentence |

### `location_extraction_runs` / `locations`
One row in `location_extraction_runs` per page. One row in `locations` per location found.

| Column | Type | Description |
|---|---|---|
| `place_name` | TEXT | Name as written in the document |
| `type` | TEXT | city, county, state, plantation, military_post, cemetery, etc. |
| `city` | TEXT | or `--` |
| `county` | TEXT | or `--` |
| `state` | TEXT | or `--` |
| `country` | TEXT | or `--` |
| `context` | TEXT | How this location appears |
| `reference` | TEXT | Exact sentence |

---

## S3 / CloudFront Storage

All images, transcription text files, and stories are stored in AWS S3 and served via a CloudFront CDN distribution. Nothing is written to local disk by the pipeline.

### S3 bucket structure

```
usct-pension-files/
├── images/
│   └── {SoldierName}/
│       └── {SoldierName}-{page:03d}.jpg     e.g. Abrams_Henry/Abrams_Henry-001.jpg
├── transcriptions/
│   └── {SoldierName}/
│       └── {SoldierName}-{page:03d}.txt
└── stories/
    └── {SoldierName}/
        ├── gemini.md
        ├── openai.md
        └── anthropic.md
```

### Public URLs

All files are publicly accessible via CloudFront HTTPS. The base URL is stored in `CLOUDFRONT_BASE_URL` in your `.env`. Example:

```
https://d49k6q6w27fis.cloudfront.net/images/Abrams_Henry/Abrams_Henry-001.jpg
```

CloudFront URLs are stored in the `transcriptions` and `stories` tables and are the source of truth for Zooniverse image references.

---

## Weaviate Collection — `CivilWarPensionPage`

All transcribed pages are embedded and stored for semantic search.

| Property | Type | Description |
|---|---|---|
| `text` | text | Chunk content |
| `transcription_id` | int | FK → `transcriptions.id` |
| `pdf_file` | text | Source PDF path |
| `pdf_stem` | text | Filename without extension |
| `page` | int | Page number |
| `chunk_index` | int | 0-based chunk index within the page |
| `total_chunks` | int | Total chunks for this page |

> Chunks are split at paragraph boundaries, max 5,000 characters, with ~400-character overlap.
