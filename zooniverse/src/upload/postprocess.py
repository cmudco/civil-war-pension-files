import csv
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from pathlib import PureWindowsPath

from db_queries import validate_column_name
from transcript_formatter import normalize_full_transcript

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = REPO_ROOT.parent
EXPORT_FILE = Path(os.getenv("EXPORT_FILE", REPO_ROOT / "dataset/classification_export.csv"))
DB_PATH = Path(os.getenv("TRANSCRIBER_DB_PATH", WORKSPACE_ROOT / "transcriber_db.db"))
VALIDATED_OUTPUT_COLUMN = os.getenv("VALIDATED_OUTPUT_COLUMN", "zooniverse_validated1")


def normalize_pdf_key(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def parse_created_at(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S UTC")


def extract_corrected_text(annotations: list[dict], metadata: dict) -> str | None:
    for task in annotations:
        if task.get("taskType") == "textFromSubject":
            value = task.get("value")
            if isinstance(value, str):
                value = value.strip()
                if value:
                    return value
        value = task.get("value")
        if isinstance(value, str):
            normalized = value.strip()
            if normalized and normalized.casefold() not in {"yes", "no"}:
                return normalized

    fallback_text = metadata.get("AI Transcript")
    if isinstance(fallback_text, str):
        fallback_text = fallback_text.strip()
        if fallback_text:
            return fallback_text

    return None


def extract_metadata(subject_data: dict) -> dict:
    subject_id = next(iter(subject_data))
    return subject_data[subject_id]


def build_transcription_lookup(db_path: Path) -> dict[tuple[str, int], int]:
    lookup: dict[tuple[str, int], int] = {}
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, pdf_file, page
            FROM transcriptions
            """
        ).fetchall()

    for row in rows:
        pdf_stem = PureWindowsPath(row["pdf_file"]).stem
        key = (normalize_pdf_key(pdf_stem), int(row["page"]))
        lookup[key] = int(row["id"])
    return lookup


def parse_transcription_id(metadata: dict, transcription_lookup: dict[tuple[str, int], int]) -> int | None:
    raw_id = metadata.get("transcription_id")
    if raw_id is None or str(raw_id).strip() == "":
        pdf_value = metadata.get("pdf")
        page_value = metadata.get("page")
        if pdf_value is None or page_value is None:
            return None
        try:
            page = int(str(page_value).strip())
        except ValueError:
            return None
        return transcription_lookup.get((normalize_pdf_key(str(pdf_value)), page))
    return int(raw_id)


def ensure_validated_output_column(db_path: Path, column_name: str) -> bool:
    column_name = validate_column_name(column_name)
    with sqlite3.connect(db_path) as conn:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(transcriptions)").fetchall()]
        if column_name not in columns:
            conn.execute(f"ALTER TABLE transcriptions ADD COLUMN {column_name} TEXT")
            conn.commit()
            return True
    return False


def load_validated_texts(
    export_file: Path,
    transcription_lookup: dict[tuple[str, int], int],
) -> dict[int, tuple[datetime, str]]:
    validated_texts: dict[int, tuple[datetime, str]] = {}

    with export_file.open(newline="", encoding="utf8") as handle:
        reader = csv.DictReader(handle)

        for row in reader:
            annotations = json.loads(row["annotations"])
            subject_data = json.loads(row["subject_data"])
            metadata = extract_metadata(subject_data)

            corrected_text = extract_corrected_text(annotations, metadata)
            if not corrected_text:
                continue

            transcription_id = parse_transcription_id(metadata, transcription_lookup)
            if transcription_id is None:
                continue

            normalized_text = normalize_full_transcript(corrected_text)
            if normalized_text:
                created_at = parse_created_at(row["created_at"])
                existing = validated_texts.get(transcription_id)
                if existing is None or created_at >= existing[0]:
                    validated_texts[transcription_id] = (created_at, normalized_text)

    return validated_texts


def write_validated_output(
    db_path: Path,
    validated_texts: dict[int, tuple[datetime, str]],
    column_name: str,
) -> int:
    column_name = validate_column_name(column_name)
    updated = 0

    with sqlite3.connect(db_path) as conn:
        for transcription_id, (_, validated_text) in validated_texts.items():
            conn.execute(
                f"""
                UPDATE transcriptions
                SET {column_name} = ?
                WHERE id = ?
                """,
                (validated_text, transcription_id),
            )
            updated += 1
        conn.commit()

    return updated


def main():
    if not EXPORT_FILE.exists():
        raise FileNotFoundError(f"Classification export not found: {EXPORT_FILE}")
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")

    added_column = ensure_validated_output_column(DB_PATH, VALIDATED_OUTPUT_COLUMN)
    transcription_lookup = build_transcription_lookup(DB_PATH)
    validated_texts = load_validated_texts(EXPORT_FILE, transcription_lookup)
    updated = write_validated_output(DB_PATH, validated_texts, VALIDATED_OUTPUT_COLUMN)

    if added_column:
        print(f"Added new output column to transcriptions: {VALIDATED_OUTPUT_COLUMN}")
    print(f"Loaded validated text for {len(validated_texts)} transcriptions from {EXPORT_FILE}")
    print(f"Updated {VALIDATED_OUTPUT_COLUMN} for {updated} transcriptions in {DB_PATH}")


if __name__ == "__main__":
    main()
