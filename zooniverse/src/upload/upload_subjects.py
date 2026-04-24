import csv
import io
import mimetypes
import os
from pathlib import Path
from urllib.parse import urlparse

from panoptes_client import Panoptes, Project, Subject, SubjectSet
from panoptes_client.panoptes import PanoptesAPIException
from panoptes_client.set_member_subject import SetMemberSubject

REPO_ROOT = Path(__file__).resolve().parents[2]
USERNAME = os.getenv("ZOONIVERSE_USERNAME", "usct_pension_files")
PASSWORD = os.getenv("ZOONIVERSE_PASSWORD", "usct2026")
PROJECT_ID = int(os.getenv("ZOONIVERSE_PROJECT_ID", "32086"))
SUBJECT_SET_NAME = os.getenv("SUBJECT_SET_NAME", "Initial Transcription Review")
MANIFEST_PATH = Path(os.getenv("MANIFEST_PATH", REPO_ROOT / "dataset/manifest.csv"))
BATCH_SIZE = int(os.getenv("SUBJECT_SET_BATCH_SIZE", "25"))
RESUME_SKIP_COUNT = int(os.getenv("RESUME_SKIP_COUNT", "0"))


def guess_mime_type(image_url: str) -> str:
    path = urlparse(image_url).path
    mime_type, _ = mimetypes.guess_type(path)
    if mime_type is None or not mime_type.startswith("image/"):
        raise ValueError(f"Could not determine image MIME type from URL: {image_url}")
    return mime_type


def create_subject_set(project: Project, display_name: str) -> SubjectSet:
    subject_set = SubjectSet()
    subject_set.links.project = project
    subject_set.display_name = display_name
    subject_set.save()
    print(f"Created subject set: {display_name} (id={subject_set.id})")
    return subject_set


def get_or_create_subject_set(project: Project, display_name: str) -> SubjectSet:
    existing_sets = SubjectSet.where(project_id=project.id, display_name=display_name)
    for existing_set in existing_sets:
        print(f"Using existing subject set: {display_name} (id={existing_set.id})")
        return existing_set

    return create_subject_set(project, display_name)


def add_subjects_with_retry(subject_set: SubjectSet, subjects: list[Subject]) -> SubjectSet:
    if not subjects:
        return subject_set

    try:
        subject_set.add(subjects)
        return subject_set
    except PanoptesAPIException as exc:
        if "stale object" not in str(exc).lower():
            raise

        refreshed_subject_set = SubjectSet.find(subject_set.id)
        refreshed_subject_set.add(subjects)
        return refreshed_subject_set


def count_existing_subjects(subject_set: SubjectSet) -> int:
    if RESUME_SKIP_COUNT > 0:
        return RESUME_SKIP_COUNT

    count = 0
    for _ in SetMemberSubject.where(subject_set_id=subject_set.id):
        count += 1
    return count


def safe_stem(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)


def build_virtual_text_filename(row: dict[str, str]) -> str:
    pdf_stem = safe_stem(row["pdf_stem"])
    page = str(row["page"]).strip()
    transcription_id = str(row["transcription_id"]).strip()
    return f"{pdf_stem}-page{page}-tid{transcription_id}.txt"


if not MANIFEST_PATH.exists():
    raise FileNotFoundError(f"Manifest not found: {MANIFEST_PATH}")

Panoptes.connect(username=USERNAME, password=PASSWORD)
project = Project.find(PROJECT_ID)

subject_set = get_or_create_subject_set(project, SUBJECT_SET_NAME)
existing_subject_count = count_existing_subjects(subject_set)
if existing_subject_count:
    print(f"Found {existing_subject_count} existing linked subjects in '{SUBJECT_SET_NAME}'.")

count = 0
skipped = 0
pending_subjects: list[Subject] = []

with MANIFEST_PATH.open(newline="", encoding="utf-8") as handle:
    reader = csv.DictReader(handle)

    for row in reader:
        if skipped < existing_subject_count:
            skipped += 1
            continue

        image_url = row["image_url"].strip()
        if not image_url.startswith(("http://", "https://")):
            print(f"Skipping invalid image URL: {image_url}")
            continue

        try:
            mime_type = guess_mime_type(image_url)
        except ValueError as exc:
            print(f"Skipping row: {exc}")
            continue

        transcript_text = row.get("final_txt_for_upload", "")
        text_buffer = io.BytesIO(transcript_text.encode("utf-8"))
        text_buffer.name = build_virtual_text_filename(row)

        subject = Subject()
        subject.links.project = project
        subject.add_location({mime_type: image_url})
        subject.add_location(text_buffer, manual_mimetype="text/plain")

        subject.metadata["page"] = row["page"]
        subject.metadata["pdf"] = row["pdf_stem"]
        subject.metadata["pdf_file"] = row["pdf_file"]
        subject.metadata["transcription_id"] = row["transcription_id"]
        subject.metadata["source_image_url"] = image_url
        if row.get("txt_url"):
            subject.metadata["source_txt_url"] = row["txt_url"]
        subject.metadata["paired_text_file"] = build_virtual_text_filename(row)

        subject.save()
        pending_subjects.append(subject)

        if len(pending_subjects) >= BATCH_SIZE:
            subject_set = add_subjects_with_retry(subject_set, pending_subjects)
            pending_subjects.clear()

        count += 1
        print(f"Uploaded {count}: {row['pdf_stem']} page {row['page']}")

subject_set = add_subjects_with_retry(subject_set, pending_subjects)

print(
    f"Done. Uploaded {count} new subjects to subject set '{SUBJECT_SET_NAME}' "
    f"and skipped {skipped} existing subjects."
)
