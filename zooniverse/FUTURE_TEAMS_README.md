# Future Teams Readme (Zooniverse Component)

## Project Context

This project is larger than the upload scripts, but this repo mainly covers the Zooniverse validation layer.

![USCT Pension Files Project Workflow](<assets/373 Project Workflow Updated.jpg>)

Zooniverse sits between automated transcription/extraction and later research use.

## What the Zooniverse Component Does

The current Zooniverse pipeline prepares one subject per page.

Each subject contains:

- one page image
- one paired plain-text transcription file for the `TextFromSubject` task type
- a small amount of metadata for traceability

The important design choice is that the volunteer edits happen inside the Zooniverse text box, not in a metadata panel. That is why the upload script now uses paired `.txt` files instead of relying on a metadata field like `AI Transcript`.

Architecture diagram: `assets/repo_logic_flow.jpg`

![Repo Logic Flow](assets/repo_logic_flow.jpg)

## Current Data Flow

The implemented flow in this repo is:

1. `transcriptions` in SQLite stores the page text and page metadata.
2. `persons` and `locations` store extracted structured information.
3. `src/upload/build_manifest.py` queries those tables and generates `dataset/manifest.csv`.
4. The manifest points each row to a CloudFront-hosted image URL.
5. `src/upload/transcript_formatter.py` builds the text payload that volunteers will edit.
6. `src/upload/upload_subjects.py` uploads the image plus the manifest's final text payload to Zooniverse using Panoptes.
7. Volunteers review and correct text in Zooniverse.
8. `src/upload/postprocess.py` writes cleaned full-page transcription into dedicated shared-DB columns such as `zooniverse_validated1` or `zooniverse_validated2`.

In the workflow diagram, this corresponds to the path:

- `Source Transcription Database (SQLite)` -> `Manifest.csv` -> `Zooniverse` -> `Crowd Validation DB` -> `Aggregation` -> `Final Output DB`

## Validation Workflow

Use two passes:

1. Upload from `final_txt_for_upload`.
2. Postprocess into `zooniverse_validated1`.
3. Rebuild from `zooniverse_validated1`.
4. Upload again if needed.
5. Postprocess into `zooniverse_validated2`.

The script now handles exports where:

- the corrected text is in `annotations`
- or the row only records `yes` and the usable text is in `subject_data["AI Transcript"]`
- or `transcription_id` is missing and the page must be matched by `pdf` + `page`

## Why the Current Design Looks Like This

There are a few design decisions that are worth preserving unless you have a strong reason to change them.

### Images are online, not local

Images are served through CloudFront rather than uploaded from a local images directory. This reduces local storage requirements and avoids rebuilding a huge image staging area every time a batch needs to be uploaded.

### Transcription text still comes from the database

The database remains the structured source of truth for page text and extracted fields, even though the text shown in Zooniverse is uploaded as a temporary `.txt` file. In the current repo layout, the Zooniverse scripts default to the repo-root `transcriber_db.db` rather than `zooniverse/dataset/transcriber_db.db`.

### `TextFromSubject` is required

This project needs volunteer correction, not just volunteer viewing. Because of that, the workflow depends on Zooniverse's `TextFromSubject` task type. If you switch workflows, make sure you understand whether the replacement still supports preloaded editable text.

### One subject equals one page

This keeps provenance simple and aligns with the rest of the pipeline, which is page-based at the transcription, extraction, and validation stages.

## Important Files

- [src/upload/build_manifest.py](src/upload/build_manifest.py)
  Builds the S3/CloudFront-based manifest from the database.

- [src/upload/upload_subjects.py](src/upload/upload_subjects.py)
  Uploads subjects to Zooniverse in the current `TextFromSubject` format.

- [src/upload/transcript_formatter.py](src/upload/transcript_formatter.py)
  Holds the reusable formatting and editable-section parsing logic.

- [src/upload/postprocess.py](src/upload/postprocess.py)
  Converts classification exports into cleaned validated page text.

- [dataset/manifest.csv](dataset/manifest.csv)
  Generated manifest used for upload.

- [DIETRICH_COMPUTING_README.md](DIETRICH_COMPUTING_README.md)
  More formal technical design document for the current implementation.

- [CLIENT_README.md](CLIENT_README.md)
  Client-facing explanation of the Zooniverse stage.

## Manifest Design

The manifest contains the page image URL, the text file URL, page metadata, and the final text payload uploaded to Zooniverse.

## Online Hosting Assumptions

The current S3 / CloudFront pattern is:

- base URL:
  `https://d49k6q6w27fis.cloudfront.net`
- images:
  `images/{pdf_stem}/{pdf_stem}-{page_padded}.jpg`
- transcription files:
  `transcriptions/{pdf_stem}/{pdf_stem}-{page_padded}.txt`

The current local SQLite file does not yet include `s3_image_url` or `s3_txt_url`, so the manifest builder can construct URLs automatically. If future partner-provided DBs include those columns, the script is already prepared to use them directly.

## Current Limitations

1. Inline highlights depend on prior extraction quality.
   If upstream extraction is noisy, that noise will be exposed to volunteers.

2. The final volunteer-facing text is currently materialized in the manifest rather than generated entirely at upload time.
   That keeps the upload path simple, but it means the manifest contains more than just routing metadata.

3. The current post-processing step stores cleaned page text in `zooniverse_validated1` / `zooniverse_validated2`.
   It is practical, but still not a full validation database model.

4. Previously uploaded Zooniverse subjects are not updated in place.
   If you change the text format or metadata structure, you usually need a new subject set.

5. Zooniverse is useful, but it is not an ideal scholarly annotation interface.
   It gives limited control over formatting and presentation, which makes it harder to show emphasis, better visual hierarchy, structured evidence, and richer review cues.

6. The current `zooniverse_validated1` / `zooniverse_validated2` fields are single text blobs.
   That is enough for intermediate results, but it is not the best long-term structure for downstream analysis.

## Likely Next Steps for Future Teams

If you inherit this project, these are the most likely engineering directions:

1. Move from local SQLite to the planned CMU-hosted PostgreSQL database.
2. Build the post-Zooniverse ingestion path from classification exports into a proper crowd-validation store.
3. Define an aggregation strategy for reconciling multiple volunteer edits into one validated output.
4. Decide how validated output feeds back into the final output database shown in the diagram.
5. Improve normalization of extracted people and place names before they are shown to volunteers.

## Suggestions For Improvement

These are the most promising ways to improve the system beyond the current semester's implementation:

1. Build a custom research interface.
   This is the clearest next step if the project continues. Zooniverse is excellent for quickly standing up volunteer workflows, but it has real limitations for research review. For example, you do not get strong control over formatting, cannot easily rely on bold text and richer layout cues, and cannot present image, transcription, extracted entities, and adjudication notes in a single purpose-built interface.

2. Create a better reviewer experience.
   A custom interface could show the page image next to the full transcription, highlight candidate names and places, show provenance from the extraction pipeline, and support clearer visual distinction between editable content and protected context.

3. Move from text blobs to structured validation tables.
   Instead of saving only `zooniverse_validated1` / `zooniverse_validated2` text fields, future teams could create tables for validated people, validated places, aliases, reviewer decisions, disagreement flags, and confidence notes.

4. Improve aggregation beyond majority vote.
   Majority vote is a reasonable baseline, but it can fail when volunteers partially agree, format answers differently, or split across two close variants. A stronger system could compare edits section-by-section, route low-agreement cases to manual review, or combine crowd input with model-assisted adjudication.

5. Add a dedicated internal review layer before public release.
   Before data reaches a final public search interface, it would help to have a staff or researcher-facing tool for checking uncertain matches, tracing evidence, and approving or rejecting crowd-validated outputs.

6. Strengthen operational resilience.
   Large uploads and export ingestion steps should be resumable by default. Continue improving recovery behavior, progress tracking, and provenance logging so future teams do not have to redo long-running batches after an interruption.

## Practical Advice

- Keep the page-level model unless there is a strong research reason to change it.
- Preserve traceability from Zooniverse output back to `transcription_id`, `pdf_file`, and `page`.
- Treat Zooniverse configuration as part of the system design, not as a separate manual step.
- Test new upload logic with a tiny subject set before pushing a full batch.
- Do not assume old subject sets reflect the newest text payload format.
- If you continue using Zooniverse, document the exact workflow configuration and export procedure. Much of the real system behavior depends on those settings, not just the Python scripts.

## Suggested Starting Point

If you are taking over this component, start by:

1. reading [DIETRICH_COMPUTING_README.md](DIETRICH_COMPUTING_README.md)
2. inspecting [src/upload/build_manifest.py](src/upload/build_manifest.py) and [src/upload/upload_subjects.py](src/upload/upload_subjects.py)
3. generating a small manifest batch
4. uploading a test subject set to confirm the `TextFromSubject` workflow still behaves as expected

## Bottom Line

The Zooniverse component is the bridge between automated page transcription and trustworthy research-ready text. In the project architecture, it is the main human validation step, and future teams will get the most leverage by treating it as part of a larger data pipeline rather than as a one-off upload script.
