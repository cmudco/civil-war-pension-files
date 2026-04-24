# User Testing Upload Guide

This folder is for one-off user testing uploads to the Zooniverse test project. Each test item should have:

- one image file
- one plain text transcript file
- one Python upload script

The workflow used here is the Zooniverse `TextFromSubject` task type. That means the transcript must be uploaded as a real `.txt` file paired with the image. Do not use metadata-only transcript prefills for this folder.

## Zooniverse Project

All upload scripts in this folder should target:

- Project ID: `32086`

That is the test project currently used for user testing in this repo.

## Where Files Go

User-testing assets now live under `dataset/userTesting/`:

- images in `dataset/userTesting/images/`
- transcripts in `dataset/userTesting/transcripts/`
- upload scripts in `src/user_testing/`

## Naming Pattern

For each test item, use the same base name for all files.

Example for `UT5`:

- `dataset/userTesting/images/UT5.png`
- `dataset/userTesting/transcripts/UT5.txt`
- `src/user_testing/UT5_upload.py`

## File Requirements

Image file:

- use `.png`
- name it exactly like `UT#.png`
- place it in `dataset/userTesting/images`

Transcript file:

- use `.txt`
- name it exactly like `UT#.txt`
- store plain text only
- place it in `dataset/userTesting/transcripts`

Upload script:

- use `.py`
- name it exactly like `UT#_upload.py`
- place it in `src/user_testing`

## How To Make a New Upload Script

Copy one of the existing upload scripts, such as: `src/user_testing/UT3_upload.py`


Then update the UT number in these places:

- `SUBJECT_SET_NAME = "UT5"`
- `IMAGE_PATH = ASSET_DIR / "images/UT5.png"`
- `TRANSCRIPT_PATH = ASSET_DIR / "transcripts/UT5.txt"`
- `subject.metadata["pdf"] = "UT5"`
- `subject.metadata["pdf_file"] = "UT5.png"`
- `subject.metadata["transcription_id"] = "UT5"`

Keep these parts unchanged unless the project setup changes:

- `PROJECT_ID = int(os.getenv("ZOONIVERSE_PROJECT_ID", "32086"))`
- `get_or_create_subject_set(...)`
- `subject.add_location(str(IMAGE_PATH))`
- `subject.add_location(str(TRANSCRIPT_PATH), manual_mimetype="text/plain")`

The second `add_location(...)` call is important. It uploads the `.txt` file as a paired subject file, which is what `TextFromSubject` needs in order to preload the transcription text in Zooniverse.

## How To Run an Upload

Open PowerShell in the repo root:

Run the script like this:

```powershell
python src\user_testing\UT5_upload.py
```

Expected output will look like one of these:

- `Created subject set: UT5 (id=...)`
- `Using existing subject set: UT5 (id=...)`

Then:

- `Uploaded subject ... to subject set 'UT5'.`

## If You Need a Fresh Subject Set Name

If you want to test a new upload without reusing the same subject set name, run:

```powershell
$env:SUBJECT_SET_NAME="UT5 retry"
python src\user_testing\UT5_upload.py
```

This is useful if you want to make sure you are seeing the latest uploaded test subject in Zooniverse.

## What To Click In Zooniverse

1. Go to `https://www.zooniverse.org`
2. Sign in with the project account
3. Click profile in the top right
4. Click `Build a Project`
5. Open `usctPensionFilesTestProject`
6. Confirm you are in project `32086`

## Check the Subject Set

1. In the left sidebar, click `Subject Sets`
2. Find the new set, such as `UT5`
3. Open it
4. Confirm it contains the uploaded subject

## Link the Subject Set to the Workflow

If the subject set is not already linked:

1. In the left sidebar, click `Workflows`
2. Open the testing workflow
3. Find the `Subject Sets` section
4. Click `Link subject sets`
5. Select the new subject set
6. Click `Save changes`

## Confirm the Workflow Type

This folder assumes the workflow uses the Zooniverse `TextFromSubject` task type.

That matters because:

- the image is one subject file
- the transcript `.txt` file is the paired second subject file
- the text box is expected to preload from that subject text file

If the workflow is not `TextFromSubject`, the transcript may not auto-fill even if the upload script succeeds.

## Test in Classify

1. Click `View project`
2. Click `Classify`
3. Open the new subject

Expected result:

- the image loads
- the transcription text is already in the text box
- the volunteer can edit the text directly

## How To Confirm the Upload Worked

The setup is correct if:

- the subject set exists
- the subject is inside the set
- the subject set is linked to the workflow
- the image appears in Classify
- the transcription text auto-loads into the text box
