import os
from pathlib import Path

from panoptes_client import Panoptes, Project, Subject, SubjectSet

USERNAME = os.getenv("ZOONIVERSE_USERNAME", "usct_pension_files")
PASSWORD = os.getenv("ZOONIVERSE_PASSWORD", "usct2026")
PROJECT_ID = int(os.getenv("ZOONIVERSE_PROJECT_ID", "32086"))

SCRIPT_DIR = Path(__file__).resolve().parent
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg")


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


def find_single_file(directory: Path, extensions: tuple[str, ...]) -> Path:
    matches = sorted(
        path for path in directory.iterdir() if path.is_file() and path.suffix.lower() in extensions
    )

    if not matches:
        joined_extensions = ", ".join(extensions)
        raise FileNotFoundError(
            f"No file with extension {joined_extensions} found in {directory}"
        )

    if len(matches) > 1:
        names = ", ".join(path.name for path in matches)
        raise ValueError(
            f"Expected exactly one file with extension {extensions} in {directory}, found: {names}"
        )

    return matches[0]


IMAGE_PATH = find_single_file(SCRIPT_DIR, IMAGE_EXTENSIONS)
TRANSCRIPT_PATH = find_single_file(SCRIPT_DIR, (".txt",))

DEFAULT_SUBJECT_NAME = IMAGE_PATH.stem
SUBJECT_SET_NAME = os.getenv("SUBJECT_SET_NAME", DEFAULT_SUBJECT_NAME)

Panoptes.connect(username=USERNAME, password=PASSWORD)
project = Project.find(PROJECT_ID)
subject_set = get_or_create_subject_set(project, SUBJECT_SET_NAME)

subject = Subject()
subject.links.project = project
subject.add_location(str(IMAGE_PATH))
subject.add_location(str(TRANSCRIPT_PATH), manual_mimetype="text/plain")

subject.metadata["page"] = "1"
subject.metadata["pdf"] = DEFAULT_SUBJECT_NAME
subject.metadata["pdf_file"] = IMAGE_PATH.name
subject.metadata["transcription_id"] = TRANSCRIPT_PATH.stem
subject.metadata["source_image_path"] = str(IMAGE_PATH)
subject.metadata["txt_file"] = TRANSCRIPT_PATH.name

subject.save()
subject_set.add(subject)
subject_set.save()

print(f"Uploaded subject {subject.id} to subject set '{SUBJECT_SET_NAME}'.")
