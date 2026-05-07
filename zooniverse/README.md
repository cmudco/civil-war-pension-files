# Zooniverse Quick Start

This folder contains the Zooniverse upload and validation workflow for the USCT Pension Files project.

Use this README as a short entry point, then jump to the more detailed docs below.

## Read This First

- [CLIENT_README.md](CLIENT_README.md)
  For clients and project partners who want the high-level explanation.

- [FUTURE_TEAMS_README.md](FUTURE_TEAMS_README.md)
  For student team members who need the handoff and overall workflow.

- [DIETRICH_COMPUTING_README.md](DIETRICH_COMPUTING_README.md)
  For technical maintainers who need implementation details and schema/processing notes.

- [ZOONIVERSE_SETUP_CHECKLIST.md](ZOONIVERSE_SETUP_CHECKLIST.md)
  For the manual post-upload checks in the Zooniverse interface.

- Please contact cathyw at andrew dot cmu for any questions

## What This Folder Does

The pipeline is:

1. Read page-level text from the shared repo-root database `../transcriber_db.db`
2. Build `dataset/manifest.csv`
3. Upload subjects to Zooniverse
4. Export classifications
5. Write cleaned validated text back into new database columns such as `zooniverse_validated1`

## Key Commands

Build the manifest:

```powershell
python src\upload\build_manifest.py
```

Upload subjects:

```powershell
$env:ZOONIVERSE_USERNAME="your-zooniverse-username"
$env:ZOONIVERSE_PASSWORD="your-zooniverse-password"
$env:ZOONIVERSE_PROJECT_ID="32086"
$env:SUBJECT_SET_NAME="TextFromSubject Test"
python src\upload\upload_subjects.py
```

Postprocess a Zooniverse export back into the shared database:

```powershell
$env:EXPORT_FILE="dataset/classification_export.csv"
python src\upload\postprocess.py
```

Run a second validation pass:

```powershell
$env:TRANSCRIPT_SOURCE_FIELD="zooniverse_validated1"
python src\upload\build_manifest.py

$env:VALIDATED_OUTPUT_COLUMN="zooniverse_validated2"
python src\upload\postprocess.py
```

Use a different database file if needed:

```powershell
$env:TRANSCRIBER_DB_PATH="C:\path\to\transcriber_db.db"
python src\upload\build_manifest.py
python src\upload\postprocess.py
```

## Important Notes

- The default database is the repo-root `transcriber_db.db`, not `zooniverse/dataset/transcriber_db.db`.
- `build_manifest.py` reads from the database and writes `dataset/manifest.csv`; it does not modify the database.
- `postprocess.py` does modify the database and will add `zooniverse_validated1` by default if that field does not already exist.
- The upload flow assumes the Zooniverse project is configured with the `TextFromSubject` task type.