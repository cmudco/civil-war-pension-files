import sqlite3
from pathlib import Path


AUTO_TRANSCRIPT_SOURCE_FIELD = "AUTO"
AUTO_TRANSCRIPT_SOURCE_CANDIDATES = (
    "validated2",
    "validated1",
    "verified_transcription",
    "final_txt_for_upload",
    "result",
)


def get_transcription_columns(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("PRAGMA table_info(transcriptions)").fetchall()
    return {row[1] for row in rows}


def validate_column_name(column_name: str) -> str:
    if not column_name.isidentifier():
        raise ValueError(f"Invalid column name: {column_name}")
    return column_name


def resolve_transcript_source_sql(columns: set[str], transcript_source_field: str) -> tuple[str, str]:
    normalized = (transcript_source_field or AUTO_TRANSCRIPT_SOURCE_FIELD).strip()

    if normalized.upper() == AUTO_TRANSCRIPT_SOURCE_FIELD:
        available_candidates = [
            column_name
            for column_name in AUTO_TRANSCRIPT_SOURCE_CANDIDATES
            if column_name in columns
        ]
        if not available_candidates:
            raise ValueError(
                "No supported transcription text column found in transcriptions table. "
                f"Tried: {', '.join(AUTO_TRANSCRIPT_SOURCE_CANDIDATES)}"
            )

        coalesce_args = [f"NULLIF(TRIM({column_name}), '')" for column_name in available_candidates]
        sql = f"COALESCE({', '.join(coalesce_args)}, '')"
        return sql, "AUTO -> " + " then ".join(available_candidates)

    column_name = validate_column_name(normalized)
    if column_name not in columns:
        raise ValueError(
            f"Column '{column_name}' not found in transcriptions table"
        )
    return column_name, column_name


def fetch_transcriptions(db_path: Path, transcript_source_field: str = AUTO_TRANSCRIPT_SOURCE_FIELD):
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        columns = get_transcription_columns(conn)
        has_s3_image_url = "s3_image_url" in columns
        has_s3_txt_url = "s3_txt_url" in columns
        transcript_source_sql, resolved_source_description = resolve_transcript_source_sql(
            columns,
            transcript_source_field,
        )

        query = """
            SELECT
                id AS transcription_id,
                pdf_file,
                page,
                txt_file,
                {transcript_source_sql} AS transcript_source_text
        """
        query = query.format(transcript_source_sql=transcript_source_sql)
        if has_s3_image_url:
            query += ", s3_image_url"
        if has_s3_txt_url:
            query += ", s3_txt_url"
        query += """
            FROM transcriptions
            ORDER BY pdf_file, page
        """

        return (
            conn.execute(query).fetchall(),
            has_s3_image_url,
            has_s3_txt_url,
            resolved_source_description,
        )


def fetch_people_by_transcription(db_path: Path) -> dict[int, list[sqlite3.Row]]:
    query = """
        SELECT
            transcription_id,
            first_name,
            middle_name,
            middle_initial,
            last_name,
            prefix,
            suffix,
            title
        FROM persons
        ORDER BY transcription_id, id
    """
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query).fetchall()

    grouped: dict[int, list[sqlite3.Row]] = {}
    for row in rows:
        grouped.setdefault(row["transcription_id"], []).append(row)
    return grouped


def fetch_locations_by_transcription(db_path: Path) -> dict[int, list[sqlite3.Row]]:
    query = """
        SELECT
            transcription_id,
            place_name,
            type,
            city,
            county,
            state
        FROM locations
        ORDER BY transcription_id, id
    """
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query).fetchall()

    grouped: dict[int, list[sqlite3.Row]] = {}
    for row in rows:
        grouped.setdefault(row["transcription_id"], []).append(row)
    return grouped
