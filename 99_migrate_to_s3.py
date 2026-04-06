#!/usr/bin/env python3
"""
99_migrate_to_s3.py

One-off migration: uploads existing local images, transcriptions, and stories
to S3 and records the CloudFront URLs in the database.

Adds new columns to `transcriptions` and creates a `stories` table on first run.

Usage:
    python 99_migrate_to_s3.py                  # migrate everything
    python 99_migrate_to_s3.py --limit 10       # migrate next 10 files per type (for testing)
    python 99_migrate_to_s3.py --dry-run        # preview only, no S3 writes, no DB changes
    python 99_migrate_to_s3.py --dry-run --limit 5

Required .env vars:
    AWS_ACCESS_KEY_ID
    AWS_SECRET_ACCESS_KEY
    S3_BUCKET_NAME
    CLOUDFRONT_BASE_URL   e.g. https://d1abc123xyz.cloudfront.net

Optional .env vars:
    AWS_REGION            default: us-east-1
"""

import argparse
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv
import os

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DB_FILE = "transcriber_db.db"
IMAGES_DIR = Path("images")
TRANSCRIPTIONS_DIR = Path("transcriptions")
STORIES_DIR = Path("stories")

AWS_ACCESS_KEY_ID     = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION            = os.getenv("AWS_REGION", "us-east-1")
S3_BUCKET_NAME        = os.getenv("S3_BUCKET_NAME")
CLOUDFRONT_BASE_URL   = (os.getenv("CLOUDFRONT_BASE_URL") or "").rstrip("/")

# Matches local filenames like "Abraham_John_page1.jpg" or "Abraham_John_page12.txt"
_PAGE_RE = re.compile(r"^(.+)_page(\d+)\.(jpg|txt)$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def cf_url(key: str) -> str:
    return f"{CLOUDFRONT_BASE_URL}/{key}"


def image_s3_key(stem: str, page: int) -> str:
    return f"images/{stem}/{stem}-{page:03d}.jpg"


def txt_s3_key(stem: str, page: int) -> str:
    return f"transcriptions/{stem}/{stem}-{page:03d}.txt"


def story_s3_key(pdf_stem: str, model: str) -> str:
    return f"stories/{pdf_stem}/{model}.md"


def parse_page_filename(name: str) -> tuple[str, int, str] | None:
    """Parse '{stem}_page{N}.{ext}' → (stem, page_num, ext) or None."""
    m = _PAGE_RE.match(name)
    if not m:
        return None
    return m.group(1), int(m.group(2)), m.group(3).lower()


def upload(s3_client, local_path: Path, key: str, content_type: str, dry_run: bool) -> bool:
    if dry_run:
        print(f"    [DRY RUN] {local_path}  →  s3://{S3_BUCKET_NAME}/{key}")
        return True
    try:
        s3_client.upload_file(
            str(local_path),
            S3_BUCKET_NAME,
            key,
            ExtraArgs={"ContentType": content_type},
        )
        return True
    except ClientError as e:
        print(f"    ERROR uploading {local_path}: {e}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# DB schema migration
# ---------------------------------------------------------------------------

def migrate_schema(con: sqlite3.Connection):
    """Idempotent: adds new columns and creates stories table if missing."""
    new_cols = [
        ("s3_image_key",           "TEXT"),
        ("s3_image_url",           "TEXT"),
        ("s3_txt_key",             "TEXT"),
        ("s3_txt_url",             "TEXT"),
        ("zooniverse_subject_id",  "TEXT"),
        ("verified_transcription", "TEXT"),
        ("verified_at",            "TEXT"),
    ]
    for col, col_type in new_cols:
        try:
            con.execute(f"ALTER TABLE transcriptions ADD COLUMN {col} {col_type}")
        except sqlite3.OperationalError:
            pass  # column already exists

    con.execute("""
        CREATE TABLE IF NOT EXISTS stories (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT    NOT NULL,
            pdf_stem   TEXT    NOT NULL,
            model      TEXT    NOT NULL,
            s3_key     TEXT,
            s3_url     TEXT,
            content    TEXT
        )
    """)
    con.commit()
    print("DB schema ready.")


# ---------------------------------------------------------------------------
# Build lookup: (stem, page) → transcription row id
# ---------------------------------------------------------------------------

def build_lookup(con: sqlite3.Connection) -> dict[tuple[str, int], int]:
    """Map (pdf_stem_underscored, page) → transcriptions.id for fast matching."""
    lookup: dict[tuple[str, int], int] = {}
    for row_id, pdf_file, page in con.execute(
        "SELECT id, pdf_file, page FROM transcriptions"
    ):
        stem = Path(pdf_file).stem.replace(" ", "_")
        lookup[(stem, page)] = row_id
    return lookup


# ---------------------------------------------------------------------------
# Per-type migration
# ---------------------------------------------------------------------------

def migrate_images(con: sqlite3.Connection, s3_client, lookup: dict, dry_run: bool, limit: int | None = None):
    files = sorted(IMAGES_DIR.glob("*.jpg"))
    print(f"\n{'='*60}")
    print(f"IMAGES  ({len(files)} .jpg files in {IMAGES_DIR}/)")
    if limit:
        print(f"  Limit: {limit} files")
    print("=" * 60)

    uploaded = already_done = failed = unrecognized = 0

    for f in files:
        if limit and uploaded >= limit:
            print(f"  Limit of {limit} reached, stopping.")
            break
        parsed = parse_page_filename(f.name)
        if not parsed:
            print(f"  SKIP (unrecognized filename): {f.name}")
            unrecognized += 1
            continue

        stem, page, _ = parsed
        key = image_s3_key(stem, page)
        url = cf_url(key)

        # Already uploaded?
        row_id = lookup.get((stem, page))
        if row_id:
            existing = con.execute(
                "SELECT s3_image_url FROM transcriptions WHERE id = ?", (row_id,)
            ).fetchone()
            if existing and existing[0]:
                already_done += 1
                continue

        ok = upload(s3_client, f, key, "image/jpeg", dry_run)
        if ok:
            uploaded += 1
            print(f"  OK  {f.name}  →  {url}")
            if not dry_run and row_id:
                con.execute(
                    "UPDATE transcriptions SET s3_image_key=?, s3_image_url=? WHERE id=?",
                    (key, url, row_id),
                )
                con.commit()
        else:
            failed += 1

    print(f"\n  Results: {uploaded} uploaded | {already_done} already done | "
          f"{failed} failed | {unrecognized} unrecognized filenames")


def migrate_transcriptions(con: sqlite3.Connection, s3_client, lookup: dict, dry_run: bool, limit: int | None = None):
    files = sorted(TRANSCRIPTIONS_DIR.glob("*.txt"))
    print(f"\n{'='*60}")
    print(f"TRANSCRIPTIONS  ({len(files)} .txt files in {TRANSCRIPTIONS_DIR}/)")
    if limit:
        print(f"  Limit: {limit} files")
    print("=" * 60)

    uploaded = already_done = failed = unrecognized = 0

    for f in files:
        if limit and uploaded >= limit:
            print(f"  Limit of {limit} reached, stopping.")
            break
        parsed = parse_page_filename(f.name)
        if not parsed:
            print(f"  SKIP (unrecognized filename): {f.name}")
            unrecognized += 1
            continue

        stem, page, _ = parsed
        key = txt_s3_key(stem, page)
        url = cf_url(key)

        row_id = lookup.get((stem, page))
        if row_id:
            existing = con.execute(
                "SELECT s3_txt_url FROM transcriptions WHERE id = ?", (row_id,)
            ).fetchone()
            if existing and existing[0]:
                already_done += 1
                continue

        ok = upload(s3_client, f, key, "text/plain; charset=utf-8", dry_run)
        if ok:
            uploaded += 1
            print(f"  OK  {f.name}  →  {url}")
            if not dry_run and row_id:
                con.execute(
                    "UPDATE transcriptions SET s3_txt_key=?, s3_txt_url=? WHERE id=?",
                    (key, url, row_id),
                )
                con.commit()
        else:
            failed += 1

    print(f"\n  Results: {uploaded} uploaded | {already_done} already done | "
          f"{failed} failed | {unrecognized} unrecognized filenames")


def migrate_stories(con: sqlite3.Connection, s3_client, dry_run: bool, limit: int | None = None):
    story_files = sorted(STORIES_DIR.rglob("*.md"))
    print(f"\n{'='*60}")
    print(f"STORIES  ({len(story_files)} .md files under {STORIES_DIR}/)")
    if limit:
        print(f"  Limit: {limit} files")
    print("=" * 60)

    uploaded = already_done = failed = 0

    for f in story_files:
        if limit and uploaded >= limit:
            print(f"  Limit of {limit} reached, stopping.")
            break
        # Expected structure: stories/{soldier_folder}/{model}.md
        pdf_stem = f.parent.name
        model = f.stem  # e.g. "gemini", "openai", "anthropic"
        key = story_s3_key(pdf_stem, model)
        url = cf_url(key)

        existing = con.execute(
            "SELECT id FROM stories WHERE s3_key = ?", (key,)
        ).fetchone()
        if existing:
            already_done += 1
            continue

        ok = upload(s3_client, f, key, "text/markdown; charset=utf-8", dry_run)
        if ok:
            uploaded += 1
            print(f"  OK  {f.relative_to(STORIES_DIR)}  →  {url}")
            if not dry_run:
                content = f.read_text(encoding="utf-8")
                con.execute("""
                    INSERT INTO stories (created_at, pdf_stem, model, s3_key, s3_url, content)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (datetime.now(timezone.utc).isoformat(), pdf_stem, model, key, url, content))
                con.commit()
        else:
            failed += 1

    print(f"\n  Results: {uploaded} uploaded | {already_done} already done | {failed} failed")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Migrate local images, transcriptions, and stories to S3."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be uploaded without writing to S3 or the database.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Only upload the next N files per type (images, transcriptions, stories). Useful for testing.",
    )
    args = parser.parse_args()

    # Validate required env vars
    missing = [v for v in (
        "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "S3_BUCKET_NAME", "CLOUDFRONT_BASE_URL"
    ) if not os.getenv(v)]
    if missing:
        print(f"ERROR: Missing required .env vars: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        print("\n" + "!" * 60)
        print("  DRY RUN MODE")
        print("  No files will be uploaded. No DB changes will be made.")
        print("!" * 60 + "\n")

    s3_client = boto3.client(
        "s3",
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name=AWS_REGION,
    )

    con = sqlite3.connect(DB_FILE)

    migrate_schema(con)

    lookup = build_lookup(con)
    print(f"Loaded {len(lookup)} transcription rows from DB for matching.")

    migrate_images(con, s3_client, lookup, args.dry_run, args.limit)
    migrate_transcriptions(con, s3_client, lookup, args.dry_run, args.limit)
    migrate_stories(con, s3_client, args.dry_run, args.limit)

    con.close()

    print(f"\n{'='*60}")
    if args.dry_run:
        print("Dry run complete. Re-run without --dry-run to execute.")
    else:
        print("Migration complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
