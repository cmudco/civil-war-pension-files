import csv
import os
from pathlib import Path, PureWindowsPath
from urllib.parse import quote
from db_queries import (
    AUTO_TRANSCRIPT_SOURCE_FIELD,
    fetch_locations_by_transcription,
    fetch_people_by_transcription,
    fetch_transcriptions,
)
from transcript_formatter import format_ai_transcript

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = REPO_ROOT.parent
DB_PATH = Path(os.getenv("TRANSCRIBER_DB_PATH", WORKSPACE_ROOT / "transcriber_db.db"))
MANIFEST_PATH = Path(os.getenv("MANIFEST_PATH", REPO_ROOT / "dataset/manifest.csv"))
CLOUDFRONT_BASE_URL = os.getenv(
    "CLOUDFRONT_BASE_URL",
    "https://d49k6q6w27fis.cloudfront.net",
).rstrip("/")
IMAGE_KEY_TEMPLATE = os.getenv(
    "IMAGE_KEY_TEMPLATE",
    "images/{pdf_stem}/{pdf_stem}-{page_padded}.jpg",
)
TXT_KEY_TEMPLATE = os.getenv(
    "TXT_KEY_TEMPLATE",
    "transcriptions/{pdf_stem}/{pdf_stem}-{page_padded}.txt",
)
PAGE_PADDING = int(os.getenv("PAGE_PADDING", "3"))
FORMAT_FOR_ZOONIVERSE = os.getenv("FORMAT_FOR_ZOONIVERSE", "1").lower() not in {
    "0",
    "false",
    "no",
}
TRANSCRIPT_SOURCE_FIELD = os.getenv("TRANSCRIPT_SOURCE_FIELD", "final_txt_for_upload")
TRANSCRIPT_SOURCE_FIELD = os.getenv("TRANSCRIPT_SOURCE_FIELD", AUTO_TRANSCRIPT_SOURCE_FIELD)


def pdf_stem_from_path(pdf_file: str) -> str:
    return PureWindowsPath(pdf_file).stem


def normalize_pdf_stem(pdf_stem: str) -> str:
    return pdf_stem.replace("\\", "_").replace("/", "_").replace(" ", "_").strip()


def build_cloudfront_url(key_template: str, pdf_file: str, page: int) -> str:
    pdf_stem = normalize_pdf_stem(pdf_stem_from_path(pdf_file))
    page_padded = f"{page:0{PAGE_PADDING}d}"
    key = key_template.format(
        pdf_stem=pdf_stem,
        page=page,
        page_padded=page_padded,
    ).lstrip("/")
    return f"{CLOUDFRONT_BASE_URL}/{quote(key, safe='/')}"
def main():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")

    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)

    records, has_s3_image_url, has_s3_txt_url, resolved_source_description = fetch_transcriptions(
        DB_PATH,
        transcript_source_field=TRANSCRIPT_SOURCE_FIELD,
    )
    people_by_transcription = fetch_people_by_transcription(DB_PATH)
    locations_by_transcription = fetch_locations_by_transcription(DB_PATH)

    rows = []
    for record in records:
        pdf_file = record["pdf_file"]
        page = record["page"]
        pdf_stem = normalize_pdf_stem(pdf_stem_from_path(pdf_file))

        image_url = (
            (record["s3_image_url"] or "").strip()
            if has_s3_image_url
            else ""
        )
        txt_url = (
            (record["s3_txt_url"] or "").strip()
            if has_s3_txt_url
            else ""
        )

        if not image_url:
            image_url = build_cloudfront_url(IMAGE_KEY_TEMPLATE, pdf_file, page)
        if not txt_url:
            txt_url = build_cloudfront_url(TXT_KEY_TEMPLATE, pdf_file, page)

        transcription_id = record["transcription_id"]
        final_txt_for_upload = format_ai_transcript(
            record["transcript_source_text"] or "",
            people_by_transcription.get(transcription_id, []),
            locations_by_transcription.get(transcription_id, []),
            format_for_zooniverse=FORMAT_FOR_ZOONIVERSE,
        )

        rows.append(
            {
                "image_url": image_url,
                "txt_url": txt_url,
                "page": page,
                "pdf_file": pdf_file,
                "pdf_stem": pdf_stem,
                "transcription_id": transcription_id,
                "txt_file": record["txt_file"] or "",
                "final_txt_for_upload": final_txt_for_upload,
            }
        )

    with MANIFEST_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "image_url",
                "txt_url",
                "page",
                "pdf_file",
                "pdf_stem",
                "transcription_id",
                "txt_file",
                "final_txt_for_upload",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Manifest written: {len(rows)} subjects -> {MANIFEST_PATH}")
    print(f"Database path: {DB_PATH}")
    print(f"CloudFront base URL: {CLOUDFRONT_BASE_URL}")
    print(f"Using DB s3_image_url column: {has_s3_image_url}")
    print(f"Using DB s3_txt_url column: {has_s3_txt_url}")
    print(f"Default image key template: {IMAGE_KEY_TEMPLATE}")
    print(f"Default transcription key template: {TXT_KEY_TEMPLATE}")
    print(f"Transcript source field: {resolved_source_description}")
    print("Combined volunteer text is stored in the manifest column: final_txt_for_upload")


if __name__ == "__main__":
    main()
