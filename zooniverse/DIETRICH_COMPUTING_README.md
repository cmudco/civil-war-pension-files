# Technical Design Document

Logic flow of this repo: 

![Repo Logic Flow](assets/architecture.png)

## Project Scope

This repository supports the Zooniverse validation stage of the Civil War pension file workflow. The current design prepares page-level image and transcription data for human review in Zooniverse using the `TextFromSubject` task type.

## Current Architecture

The system now uses four main components:

1. `../transcriber_db.db`
   This repo-root SQLite database is the default source of truth for page-level transcription text and extracted structured data. The scripts can still be pointed elsewhere with `TRANSCRIBER_DB_PATH`.

2. CloudFront / S3 image hosting
   Historical page images are served from:
   `https://d49k6q6w27fis.cloudfront.net`

3. Manifest generation
   A generated CSV manifest connects each transcription record to its image URL, transcription URL, metadata, and Zooniverse-facing editable text payload.

4. Zooniverse upload
   Subjects are uploaded to Zooniverse as paired files:
   - one remote image
   - one in-memory plain-text payload for `TextFromSubject`

5. Post-processing
   Classification exports are converted into cleaned page text and written back into validation columns in SQLite.

## Core Workflow

The intended flow is:

1. A page is transcribed and stored in the `transcriptions` table.
2. People and locations are extracted into `persons` and `locations`.
3. `src/upload/build_manifest.py` reads the database and produces `dataset/manifest.csv`.
4. `src/upload/upload_subjects.py` reads that manifest.
6. For each row, the script:
   - links the remote page image
   - uploads the final text payload as the paired `TextFromSubject` text source
   - stores selected metadata on the Zooniverse subject
7. Volunteers see the image and preloaded text in the transcription interface and can directly correct it.
7. `src/upload/postprocess.py` reads the classification export, removes inline `<<...>>` markers, and writes cleaned page text into Zooniverse-specific columns such as `zooniverse_validated1` or `zooniverse_validated2`.

## Why `TextFromSubject`

The current workflow uses Zooniverse's `TextFromSubject` task type rather than metadata-only transcript display.

This choice matters because:

- the text appears directly in the editable text box
- volunteers can correct the draft immediately
- the transcription is treated as subject content, not just reference metadata
- the workflow matches Zooniverse guidance for text-correction projects

In practice, this means each Zooniverse subject must contain:

- an image file
- a plain-text file

The plain-text file is uploaded as a paired subject location, not as an `AI Transcript` metadata field.

## Online Storage Design

The image hosting pattern provided by project partners is:

- Base URL:
  `https://d49k6q6w27fis.cloudfront.net`
- Image key pattern:
  `images/{pdf_stem}/{pdf_stem}-{page_padded}.jpg`
- Transcription key pattern:
  `transcriptions/{pdf_stem}/{pdf_stem}-{page_padded}.txt`

Example:

`https://d49k6q6w27fis.cloudfront.net/images/Abbs_Wilkins/Abbs_Wilkins-001.jpg`

This allows Zooniverse to fetch page images directly over HTTPS without local image staging.

## Database Usage

The key table for upload is `transcriptions`.

Important fields:

- `id`
- `pdf_file`
- `page`
- `txt_file`
- `final_txt_for_upload`
- `zooniverse_validated1` / `zooniverse_validated2`

Additional extracted data comes from:

- `persons`
- `locations`

The current local SQLite file does not yet contain `s3_image_url` or `s3_txt_url`, so `src/upload/build_manifest.py` supports both cases:

- if those columns exist in a future DB, it uses them directly
- otherwise it constructs CloudFront URLs from the naming convention

This keeps the pipeline compatible with both the current local DB and an updated DB from partners.

## Zooniverse Text Payload Format

The uploaded text is the page transcription with inline `<<...>>` highlights around detected people and locations. After review, postprocessing removes those markers before writing validated text back to the database.

## Script Responsibilities

### `src/upload/build_manifest.py`

Responsibilities:

- open the SQLite database
- read transcription rows
- read extracted people and locations
- derive or reuse CloudFront URLs
- call the transcript formatter to build the Zooniverse text payload
- write `dataset/manifest.csv`

Output columns:

- `image_url`
- `txt_url`
- `page`
- `pdf_file`
- `pdf_stem`
- `transcription_id`
- `txt_file`
- `final_txt_for_upload`

This field holds the full formatted `TextFromSubject` text payload used for upload.

### `src/upload/upload_subjects.py`

Responsibilities:

- connect to Zooniverse using Panoptes
- create or reuse a subject set
- read the generated manifest
- upload one remote image plus one paired text payload per subject
- attach core metadata
- support resume behavior by skipping rows that are already linked or by using a manual skip count during recovery

### `src/upload/transcript_formatter.py`

Responsibilities:

- format the volunteer-facing names/places block
- append the protected transcription context
- remove inline entity tags and normalize full-page text for post-processing

### `src/upload/postprocess.py`

Responsibilities:

- read a Zooniverse classification export CSV
- recover the page either from `transcription_id` or from `pdf` + `page`
- use the corrected text from `annotations`, or fall back to `subject_data["AI Transcript"]` when the row only records a confirmation like `yes`
- strip inline `<<...>>` tags and write cleaned page text into configurable Zooniverse output columns

## Validation Workflow

The intended review loop is:

1. Build from `final_txt_for_upload` and upload to Zooniverse.
2. Export classifications and write the cleaned result into `zooniverse_validated1`.
3. Build again using `TRANSCRIPT_SOURCE_FIELD=zooniverse_validated1`.
4. Upload a second review round if needed.
5. Export again and write the cleaned result into `zooniverse_validated2`.

Useful commands:

```powershell
$env:TRANSCRIPT_SOURCE_FIELD="final_txt_for_upload"
python src\upload\build_manifest.py

$env:EXPORT_FILE="dataset/classification_export.csv"
python src\upload\postprocess.py
```

If a teammate keeps the database somewhere else, override it directly:

```powershell
$env:TRANSCRIBER_DB_PATH="C:\path\to\transcriber_db.db"
python src\upload\build_manifest.py
python src\upload\postprocess.py
```

Second pass:

```powershell
$env:TRANSCRIPT_SOURCE_FIELD="zooniverse_validated1"
python src\upload\build_manifest.py

$env:VALIDATED_OUTPUT_COLUMN="zooniverse_validated2"
python src\upload\postprocess.py
```

## Operational Notes For Teams

- The upload/post-process loop assumes one Zooniverse subject maps to one page.
- Recent exports may omit `transcription_id`, so postprocessing falls back to `pdf` + `page`.
- If a run is interrupted, `src/upload/upload_subjects.py` now supports resuming in an existing subject set rather than forcing a brand new one.
- Zooniverse exports should be treated as append-only snapshots. Keep a copy of the exact export used for any database update so the provenance of `zooniverse_validated1` / `zooniverse_validated2` is recoverable later.

## Configuration

### Manifest builder

Supported environment variables:

- `TRANSCRIBER_DB_PATH`
  Defaults to the repo-root `transcriber_db.db`
- `MANIFEST_PATH`
- `CLOUDFRONT_BASE_URL`
- `IMAGE_KEY_TEMPLATE`
- `TXT_KEY_TEMPLATE`
- `PAGE_PADDING`
- `FORMAT_FOR_ZOONIVERSE`
- `TRANSCRIPT_SOURCE_FIELD`

### Upload script

Supported environment variables:

- `ZOONIVERSE_USERNAME`
- `ZOONIVERSE_PASSWORD`
- `ZOONIVERSE_PROJECT_ID`
- `SUBJECT_SET_NAME`
- `MANIFEST_PATH`
- `EXPORT_FILE`
- `VALIDATED_OUTPUT_COLUMN`
## Operational Assumptions

The current design assumes:

- CloudFront image URLs are public and stable
- Zooniverse can fetch the image URLs directly over HTTPS
- the target Zooniverse workflow uses `TextFromSubject`
- one subject corresponds to one page
- the local machine running the upload can read the manifest produced by the builder

## Current Limitations

1. The final volunteer-facing text is currently stored in the manifest.
   That is simple and explicit, but it means the manifest is not just lightweight routing metadata.

2. Name quality depends on prior extraction quality.
   The `People` section is drawn from the `persons` table, so OCR or extraction errors can still appear there.

3. The formatted text currently uses existing extracted people and places only.
   It does not yet perform deeper entity cleanup, spelling normalization, or deduplication beyond simple ordering and duplicate suppression.

4. The current post-processing step stores a full cleaned transcription per page, but it still uses simple majority vote rather than richer adjudication.

5. Existing uploaded subject sets are not updated in place.
   Any metadata or text-formatting change requires a new upload batch unless a separate update process is built.

## Future Direction

Several near-term changes are already anticipated:

- migration from local SQLite to hosted PostgreSQL at CMU
- use of direct `s3_image_url` / `s3_txt_url` columns when available
- storage of volunteer-corrected text in a new linked table rather than overwriting originals
- possible cleanup or normalization of extracted names and locations before manifest generation

Additional recommendations for future teams:

- Build a dedicated research interface if this workflow becomes central to the project. Zooniverse is useful for fast deployment and volunteer management, but it has real limitations for scholarly review work, including limited text formatting, weak layout control, and difficulty presenting richer evidence side-by-side.
- Consider an interface that can show bold labels, clearer section hierarchy, color cues, provenance links, and synchronized views of image, transcription, extracted entities, and prior edits.
- Store structured post-validation outputs in separate tables rather than only `zooniverse_validated1` / `zooniverse_validated2` text fields. In the long run, research workflows will benefit from explicit validated people, places, aliases, confidence notes, and reviewer provenance.
- Replace pure majority vote with a richer aggregation strategy when the scale justifies it. For example, future teams could compare volunteer edits line-by-line, flag disagreements for manual review, or combine crowd input with model-assisted adjudication.
- Add more fault-tolerant batch operations around upload and export ingestion. Large runs can fail due to network interruptions or API instability, so resume-safe workflows should be treated as a requirement rather than a convenience.
- Consider pushing validated outputs into a searchable internal review tool before building a full public-facing site. That would give researchers a place to inspect entity matches, trace evidence, and correct mistakes before publication.

The current code is structured to make those changes incremental rather than requiring a full rewrite.

## Verification Checklist

After a successful upload:

1. Confirm the new subject set exists in the Zooniverse project.
2. Link the subject set to the intended workflow.
3. Open `Classify`.
4. Verify the page image loads.
5. Verify the text box is prefilled.
6. Confirm the inline-highlighted transcription appears as expected.
7. Submit a test classification and confirm the output appears in the export.

## Summary

The present design uses SQLite as the structured source, CloudFront as the image delivery layer, a generated manifest as the handoff artifact, and Zooniverse `TextFromSubject` as the volunteer correction interface.

This design minimizes manual pairing work, supports partner-managed online storage, and keeps the pipeline compatible with future migration to hosted database infrastructure.
