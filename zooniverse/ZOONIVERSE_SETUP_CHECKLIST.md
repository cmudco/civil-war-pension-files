# Zooniverse — What to Click and What to Expect After Upload

This is after you uploaded all images.

## Step 1 — Check the Subject Set Was Created

1. Go to https://www.zooniverse.org
2. Click your username (top right) -> **Build a Project** (assumed you logged in using the username and password used by `src/upload/upload_subjects.py`)
3. Click **usctPensionFilesTestProject** (Project #32086)
4. In the left sidebar, click **Subject Sets**

**Expected:** You should see your new subject set listed with a subject count matching how many uploaded successfully (e.g. 26).


## Step 2 — Check a Subject's Metadata

1. Click into your subject set
2. Click on any subject thumbnail
3. A panel should open showing the subject details

**Expected:** You should see metadata fields:
- `page` — the page number
- `pdf` — the PDF name (e.g. `Robinson_Lucius`)
- `image_filename` — the filename
- `AI Transcript` — the draft transcript text (this is what volunteers see when they click ⓘ)

If the text box is blank or missing expected text, re-run `src/upload/build_manifest.py` and `src/upload/upload_subjects.py`.


## Step 3 — Link the Subject Set to Your Workflow

1. In the left sidebar, click **Workflows**
2. Click **Pension Files Transcription**
3. Scroll down to **Subject Sets**
4. Click **Link subject sets** and select your new subject set
5. Click **Save changes** (bottom of page)

**Expected:** The subject set name appears under the workflow's linked subject sets.


## Step 4 — Test Classify

1. Click **View project** in the left sidebar
2. Click **Classify** in the top nav
3. A document image should appear on the left

**Expected:**
- Document image loads on the left
- Task panel on the right shows the transcription text box
- Task instructions are visible (e.g. "Click the ⓘ button to view the AI draft")


## Step 5 — Check the ⓘ Info Button

1. On the classify page, look below the document image for a small **ⓘ** icon
2. Click it

**Expected:** A panel opens showing all the subject metadata including the `AI Transcript` field with the draft text for that specific page.

If the panel is empty or missing `AI Transcript`, the metadata was not uploaded correctly.


## Step 6 — Submit a Test Classification

1. Copy some text into the transcription box
2. Click **Done**

**Expected:** The next subject loads automatically. The previous subject's classification is now recorded.


## Step 7 — Check Classifications Were Recorded

1. Go back to the Project Builder
2. Click **Data Exports** in the left sidebar
3. Click **Request new classification export**
4. Wait a few minutes, then click **Download**

**Expected:** A CSV file downloads containing your test classification with columns like `subject_id`, `user_name`, `annotations`, etc.


## Common Problems and Fixes

| Problem | Likely Cause | Fix |
|---------|-------------|-----|
| Subject set missing from list | Upload script errored out | Check terminal output, re-run `src/upload/upload_subjects.py` with a new set name |
| Subject count is 0 or wrong | Images not found during upload | Check image paths in manifest, re-run `src/upload/build_manifest.py` |
| Text box not prefilled as expected | Old manifest or upload mismatch | Re-run `src/upload/build_manifest.py` then `src/upload/upload_subjects.py` |
| Classify page shows "You've seen everything" | Subject set not linked to workflow | Follow Step 3 above |
| Images not loading | File too large or wrong format | Convert to JPEG under 1 MB before upload |
