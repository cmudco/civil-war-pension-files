import os
from pathlib import Path

from panoptes_client import Panoptes, Project, Subject, SubjectSet

USERNAME = os.getenv("ZOONIVERSE_USERNAME", "usct_pension_files")
PASSWORD = os.getenv("ZOONIVERSE_PASSWORD", "usct2026")
PROJECT_ID = int(os.getenv("ZOONIVERSE_PROJECT_ID", "32086"))
SUBJECT_SET_NAME = os.getenv("SUBJECT_SET_NAME", "UT1")

REPO_ROOT = Path(__file__).resolve().parents[2]
ASSET_DIR = REPO_ROOT / "dataset/userTesting"
IMAGE_PATH = ASSET_DIR / "images/UT1.png"
TRANSCRIPT_PATH = ASSET_DIR / "transcripts/UT1.txt"


def get_or_create_subject_set(project: Project, display_name: str) -> SubjectSet:
    existing_sets = SubjectSet.where(project_id=project.id, display_name=display_name)
    for existing_set in existing_sets:
        print(f"Using existing subject set: {display_name} (id={existing_set.id})")
        return existing_set

    subject_set = SubjectSet()
    subject_set.links.project = project
    subject_set.display_name = display_name
    subject_set.save()
    print(f"Created subject set: {display_name} (id={subject_set.id})")
    return subject_set


if not IMAGE_PATH.exists():
    raise FileNotFoundError(f"Image not found: {IMAGE_PATH}")

if not TRANSCRIPT_PATH.exists():
    raise FileNotFoundError(f"Transcript not found: {TRANSCRIPT_PATH}")

Panoptes.connect(username=USERNAME, password=PASSWORD)
project = Project.find(PROJECT_ID)
subject_set = get_or_create_subject_set(project, SUBJECT_SET_NAME)

subject = Subject()
subject.links.project = project
subject.add_location(str(IMAGE_PATH))
subject.add_location(str(TRANSCRIPT_PATH), manual_mimetype="text/plain")

subject.metadata["page"] = "1"
subject.metadata["pdf"] = "UT1"
subject.metadata["pdf_file"] = "UT1.png"
subject.metadata["transcription_id"] = "UT1"
subject.metadata["source_image_path"] = str(IMAGE_PATH)
subject.metadata["txt_file"] = TRANSCRIPT_PATH.name

subject.save()
subject_set.add(subject)
subject_set.save()

print(f"Uploaded subject {subject.id} to subject set '{SUBJECT_SET_NAME}'.")
