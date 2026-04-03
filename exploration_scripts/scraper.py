#!/usr/bin/env python3
"""
IAAM USCT Pension Files Downloader
Downloads all pension application PDFs from the IAAM Omeka S site.
Uses the Omeka S REST API for clean, reliable access.
"""

import requests
import os
import json
import time
import argparse
import sqlite3
import logging
import random
from pathlib import Path
from tqdm import tqdm
from datetime import datetime

# Configuration
BASE_URL = "https://iaamcfh.omeka.net"
API_BASE = f"{BASE_URL}/api"
OUTPUT_DIR = "usct_pension_files"
METADATA_FILE = "pension_metadata.json"
DB_FILE = "pension_data.db"
LOG_FILE = "scraper.log"
MAX_WORKERS = 3  # Parallel downloads (be nice to server)

# Item set IDs for USCT Pension Applications
ITEM_SET_IDS = {
    1507: "A-B",
    1508: "C-D", 
    1509: "E-F",
    1510: "G-H",
    1511: "I-J",
    1512: "K-L",
    1518: "M-N",
    1516: "O-P",
    1519: "Q-R",
    1515: "S-T",
    1517: "W-X"
}

session = requests.Session()
session.headers.update({
    'User-Agent': 'USCT-Pension-Downloader/1.0 (Carnegie Mellon University Dietrich College research project; contact: gdcann@andrew.cmu.edu)',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9'
})

# ============================================================================
# Database Layer
# ============================================================================

def init_database(db_path):
    """Initialize SQLite database with schema."""
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL")  # Better for Windows

    # Create items table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            surname TEXT,
            item_set_id INTEGER NOT NULL,
            letter_range TEXT NOT NULL,
            metadata TEXT NOT NULL,
            date_processed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            date_modified TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'pending',
            error_message TEXT,
            UNIQUE(id)
        )
    """)

    # Create files table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            media_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            source_filename TEXT,
            file_path TEXT NOT NULL,
            file_size INTEGER,
            media_type TEXT,
            url TEXT,
            download_date TIMESTAMP,
            status TEXT DEFAULT 'pending',
            error_message TEXT,
            FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE,
            UNIQUE(media_id)
        )
    """)

    # Create logs table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            level TEXT NOT NULL,
            message TEXT NOT NULL,
            item_id INTEGER,
            media_id INTEGER,
            FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE SET NULL
        )
    """)

    # Create indexes
    conn.execute("CREATE INDEX IF NOT EXISTS idx_items_status ON items(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_items_letter_range ON items(letter_range)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_files_item_id ON files(item_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_files_status ON files(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON logs(timestamp DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_level ON logs(level)")

    conn.commit()
    return conn

def get_or_create_item(conn, item_data, item_set_id, letter_range):
    """Insert or update item in database, return (item_id, is_new)."""
    item_id = item_data.get("id")
    title = item_data.get("title", "")
    surname = "; ".join(item_data.get("surname", []))

    # Serialize metadata to JSON
    try:
        metadata_json = json.dumps(item_data)
    except (TypeError, ValueError):
        metadata_json = json.dumps({"error": "Serialization failed"})

    # Check if item exists
    cursor = conn.execute("SELECT id, status FROM items WHERE id = ?", (item_id,))
    row = cursor.fetchone()

    if row:
        # Update existing item
        conn.execute("""
            UPDATE items
            SET title=?, surname=?, metadata=?, date_modified=CURRENT_TIMESTAMP
            WHERE id=?
        """, (title, surname, metadata_json, item_id))
        return item_id, False
    else:
        # Insert new item
        conn.execute("""
            INSERT INTO items (id, title, surname, item_set_id, letter_range, metadata)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (item_id, title, surname, item_set_id, letter_range, metadata_json))
        conn.commit()
        return item_id, True

def record_file_download(conn, item_id, media_id, file_info):
    """Record file download in database."""
    # Check if file exists
    cursor = conn.execute("SELECT id FROM files WHERE media_id = ?", (media_id,))
    row = cursor.fetchone()

    if row:
        # Update existing file record
        conn.execute("""
            UPDATE files
            SET filename=?, file_path=?, file_size=?, status=?, download_date=CURRENT_TIMESTAMP
            WHERE media_id=?
        """, (
            file_info.get("filename"),
            file_info.get("file_path"),
            file_info.get("file_size"),
            file_info.get("status"),
            media_id
        ))
    else:
        # Insert new file record
        conn.execute("""
            INSERT INTO files (item_id, media_id, filename, source_filename, file_path,
                             file_size, media_type, url, download_date, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
        """, (
            item_id,
            media_id,
            file_info.get("filename"),
            file_info.get("source_filename"),
            file_info.get("file_path"),
            file_info.get("file_size"),
            file_info.get("media_type"),
            file_info.get("url"),
            file_info.get("status")
        ))
    conn.commit()

def log_to_db(conn, level, message, item_id=None, media_id=None):
    """Write log entry to database (WARNING and ERROR only)."""
    if level in ('WARNING', 'ERROR'):
        conn.execute("""
            INSERT INTO logs (level, message, item_id, media_id)
            VALUES (?, ?, ?, ?)
        """, (level, message, item_id, media_id))
        conn.commit()

def get_completed_items(conn):
    """Return set of completed item IDs for resume functionality."""
    cursor = conn.execute("SELECT id FROM items WHERE status='completed'")
    return {row[0] for row in cursor.fetchall()}

def get_statistics(conn):
    """Query database for progress statistics."""
    stats = {}

    # Count items by status
    cursor = conn.execute("SELECT COUNT(*) FROM items WHERE status='completed'")
    stats['completed_items'] = cursor.fetchone()[0]

    cursor = conn.execute("SELECT COUNT(*) FROM items WHERE status='error'")
    stats['error_items'] = cursor.fetchone()[0]

    # Count files
    cursor = conn.execute("SELECT COUNT(*) FROM files WHERE status='downloaded'")
    stats['downloaded_files'] = cursor.fetchone()[0]

    cursor = conn.execute("SELECT COUNT(*) FROM files WHERE status='exists'")
    stats['existing_files'] = cursor.fetchone()[0]

    # Count errors
    cursor = conn.execute("SELECT COUNT(*) FROM logs WHERE level='ERROR'")
    stats['error_count'] = cursor.fetchone()[0]

    return stats

# ============================================================================
# Logging Setup
# ============================================================================

def setup_logging(log_file):
    """Configure logging with file and console handlers."""
    # Create logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Remove existing handlers
    logger.handlers = []

    # File handler
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_format = logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s')
    file_handler.setFormatter(file_format)
    logger.addHandler(file_handler)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter('%(levelname)s: %(message)s')
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)

# ============================================================================
# API & Download Functions
# ============================================================================

def api_get(endpoint, params=None, min_delay=2, max_delay=10):
    """Make API request with retry logic and random delays."""
    url = f"{API_BASE}/{endpoint}"
    for attempt in range(3):
        try:
            resp = session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            if attempt == 2:
                raise
            # Random delay before retry
            delay = random.uniform(min_delay, max_delay)
            logging.info(f"Request failed (attempt {attempt + 1}/3), waiting {delay:.2f}s before retry...")
            time.sleep(delay)
    return None

def get_items_in_set(item_set_id, per_page=100, min_delay=2, max_delay=10):
    """Fetch all items from an item set via API."""
    items = []
    page = 1

    while True:
        params = {"item_set_id": item_set_id, "per_page": per_page, "page": page}
        data = api_get("items", params, min_delay=min_delay, max_delay=max_delay)

        if not data:
            break

        items.extend(data)
        logging.info(f"    Page {page}: {len(data)} items")

        if len(data) < per_page:
            break
        page += 1
        # Random delay between pages
        delay = random.uniform(min_delay, max_delay)
        time.sleep(delay)

    return items

def get_media_details(media_id):
    """Fetch media details to get download URL."""
    return api_get(f"media/{media_id}")

def extract_dc_values(item, field):
    """Extract values from Dublin Core fields."""
    values = []
    field_data = item.get(field, [])
    for v in field_data:
        if isinstance(v, dict):
            if "@value" in v:
                values.append(v["@value"])
            elif "display_title" in v:
                # This is a linked resource
                values.append(f"[Link to: {v['display_title']}]")
    return values

def extract_metadata(item):
    """Extract all relevant metadata from an item."""
    metadata = {
        "id": item.get("o:id"),
        "title": item.get("o:title"),
        "created": item.get("o:created", {}).get("@value"),
        "modified": item.get("o:modified", {}).get("@value"),
        "is_public": item.get("o:is_public"),
        # Dublin Core fields
        "dc_title": extract_dc_values(item, "dcterms:title"),
        "dc_date": extract_dc_values(item, "dcterms:date"),
        "dc_description": extract_dc_values(item, "dcterms:description"),
        "dc_creator": extract_dc_values(item, "dcterms:creator"),
        "dc_publisher": extract_dc_values(item, "dcterms:publisher"),
        "dc_coverage": extract_dc_values(item, "dcterms:coverage"),
        "dc_rights": extract_dc_values(item, "dcterms:rights"),
        # FOAF fields
        "surname": extract_dc_values(item, "foaf:surname"),
        # Media references
        "media_ids": [m.get("o:id") for m in item.get("o:media", [])],
        # Geographic data
        "locations": [],
        # Related items (cross-references)
        "related_items": []
    }
    
    # Extract geographic features
    for feature in item.get("o-module-mapping:feature", []):
        metadata["locations"].append({
            "label": feature.get("o:label"),
            "coordinates": feature.get("o-module-mapping:geography-coordinates")
        })
    
    # Extract reverse links (items that reference this one)
    reverse = item.get("@reverse", {})
    for ref in reverse.get("dcterms:description", []):
        metadata["related_items"].append({
            "id": ref.get("@id"),
            "title": ref.get("o:title")
        })
    
    return metadata

def sanitize_filename(name):
    """Create a safe filename."""
    for char in ['/', '\\', ':', '*', '?', '"', '<', '>', '|', '\n', '\r']:
        name = name.replace(char, '_')
    return name.strip()[:150]

def download_file(url, filepath):
    """Download a file."""
    resp = session.get(url, stream=True, timeout=60)
    resp.raise_for_status()
    
    with open(filepath, 'wb') as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    
    return filepath.stat().st_size

def process_item(item, set_dir, conn, item_set_id, letter_range, min_delay=2, max_delay=10):
    """Process a single item: extract metadata and download files."""
    item_id = item.get("o:id")

    # Check if already completed
    cursor = conn.execute("SELECT status FROM items WHERE id = ?", (item_id,))
    row = cursor.fetchone()
    if row and row[0] == 'completed':
        logging.info(f"Item {item_id} already completed, skipping")
        return None

    title = item.get("o:title", f"item_{item_id}")
    metadata = extract_metadata(item)
    metadata["files"] = []

    # Record item in database
    try:
        db_item_id, is_new = get_or_create_item(conn, metadata, item_set_id, letter_range)

        # Update status to in_progress
        conn.execute("UPDATE items SET status='in_progress' WHERE id=?", (item_id,))
        conn.commit()
    except Exception as e:
        logging.error(f"Failed to record item {item_id} in database: {e}")
        log_to_db(conn, 'ERROR', f"Failed to record item: {e}", item_id)
        return None

    # Process each media file
    for media_id in metadata["media_ids"]:
        try:
            # Check if file already downloaded in DB
            cursor = conn.execute("SELECT status FROM files WHERE media_id = ?", (media_id,))
            file_row = cursor.fetchone()
            if file_row and file_row[0] == 'downloaded':
                logging.info(f"  File {media_id} already downloaded, skipping")
                continue

            media = get_media_details(media_id)
            if not media:
                continue

            # Get the original file URL
            original_url = media.get("o:original_url")
            if not original_url:
                continue

            # Get filename info - prefer o:source (original upload name)
            source_filename = media.get("o:source", "")
            omeka_filename = media.get("o:filename", f"{media_id}.pdf")
            media_type = media.get("o:media_type", "")
            file_size = media.get("o:size", 0)

            # Use source filename if available, otherwise construct from title
            if source_filename:
                local_filename = sanitize_filename(source_filename)
            else:
                ext = Path(omeka_filename).suffix or ".pdf"
                local_filename = f"{sanitize_filename(title)}{ext}"
            filepath = set_dir / local_filename

            # Calculate relative path for database
            rel_path = f"{letter_range.replace('-', '_')}/{local_filename}"

            # Download if needed
            if not filepath.exists():
                size = download_file(original_url, filepath)
                status = "downloaded"
                logging.info(f"  Downloaded {local_filename} ({size // 1024} KB)")
            else:
                size = filepath.stat().st_size
                status = "exists"
                logging.info(f"  File exists: {local_filename}")

            # Record file in database
            file_info = {
                "filename": local_filename,
                "source_filename": source_filename,
                "file_path": rel_path,
                "file_size": size,
                "media_type": media_type,
                "url": original_url,
                "status": status
            }
            record_file_download(conn, item_id, media_id, file_info)

            metadata["files"].append({
                "media_id": media_id,
                "filename": local_filename,
                "source_filename": source_filename,
                "url": original_url,
                "media_type": media_type,
                "size": file_size,
                "status": status
            })

            # Random delay between files
            delay = random.uniform(min_delay, max_delay)
            time.sleep(delay)

        except Exception as e:
            error_msg = str(e)
            logging.error(f"  Failed to process media {media_id}: {error_msg}")
            log_to_db(conn, 'ERROR', f"Failed to download media: {error_msg}", item_id, media_id)
            metadata["files"].append({
                "media_id": media_id,
                "error": error_msg
            })

    # Mark item as completed
    try:
        conn.execute("UPDATE items SET status='completed' WHERE id=?", (item_id,))
        conn.commit()
    except Exception as e:
        logging.error(f"Failed to mark item {item_id} as completed: {e}")

    return metadata

def main():
    parser = argparse.ArgumentParser(description="Download USCT pension files from IAAM")
    parser.add_argument("--limit", type=int, default=None, help="Max items to download (for testing)")
    parser.add_argument("--set", type=str, default=None, help="Only process this letter range (e.g., 'A-B')")
    parser.add_argument("--min-delay", type=float, default=2.0, help="Minimum delay between requests (seconds)")
    parser.add_argument("--max-delay", type=float, default=10.0, help="Maximum delay between requests (seconds)")
    args = parser.parse_args()

    output_path = Path(OUTPUT_DIR)
    output_path.mkdir(exist_ok=True)

    # Setup logging
    log_file = output_path / LOG_FILE
    setup_logging(log_file)
    logging.info("=" * 70)
    logging.info("IAAM USCT Pension Files Downloader")
    logging.info("Carnegie Mellon University Dietrich College research project")
    if args.limit:
        logging.info(f"TEST MODE: Limiting to {args.limit} item(s)")
    if args.set:
        logging.info(f"Filtering to set: {args.set}")
    logging.info(f"Random delays: {args.min_delay:.1f}s - {args.max_delay:.1f}s")
    logging.info("=" * 70)

    # Initialize database
    db_path = output_path / DB_FILE
    conn = init_database(db_path)
    logging.info(f"Database initialized: {db_path}")

    # Get completed items for resume
    completed_items = get_completed_items(conn)
    if completed_items:
        logging.info(f"Resuming: {len(completed_items)} items already completed")

    # Filter item sets
    item_sets_to_process = [
        (id, range) for id, range in ITEM_SET_IDS.items()
        if not args.set or range == args.set
    ]

    total_processed = 0

    # Outer progress bar for item sets
    with tqdm(total=len(item_sets_to_process), desc="Item Sets", position=0, leave=True) as pbar_sets:
        for item_set_id, letter_range in item_sets_to_process:
            # Stop if we've hit the limit
            if args.limit and total_processed >= args.limit:
                break

            logging.info(f"\n[{letter_range}] Fetching item set {item_set_id}...")

            set_dir = output_path / letter_range.replace("-", "_")
            set_dir.mkdir(exist_ok=True)

            # Fetch items
            try:
                items = get_items_in_set(item_set_id, min_delay=args.min_delay, max_delay=args.max_delay)
                logging.info(f"  Found {len(items)} items in {letter_range}")
            except Exception as e:
                logging.error(f"  Failed to fetch items for {letter_range}: {e}")
                log_to_db(conn, 'ERROR', f"Failed to fetch item set: {e}")
                pbar_sets.update(1)
                continue

            # Filter out completed items
            items_to_process = [
                i for i in items
                if i.get("o:id") not in completed_items
            ]

            # Apply limit
            if args.limit:
                remaining = args.limit - total_processed
                items_to_process = items_to_process[:remaining]

            if not items_to_process:
                logging.info(f"  All items in {letter_range} already completed, skipping")
                pbar_sets.update(1)
                continue

            logging.info(f"  Processing {len(items_to_process)} items in {letter_range}")

            # Inner progress bar for items in current set
            with tqdm(total=len(items_to_process),
                     desc=f"[{letter_range}]",
                     position=1,
                     leave=False) as pbar_items:

                for item in items_to_process:
                    try:
                        result = process_item(item, set_dir, conn, item_set_id, letter_range,
                                            args.min_delay, args.max_delay)
                        if result:
                            pbar_items.set_postfix_str(f"{item.get('o:title', 'Unknown')[:30]}")
                        pbar_items.update(1)

                    except Exception as e:
                        logging.error(f"Failed to process item {item.get('o:id')}: {e}")
                        log_to_db(conn, 'ERROR', str(e), item.get("o:id"))
                        pbar_items.update(1)

                    total_processed += 1

                    # Check limit
                    if args.limit and total_processed >= args.limit:
                        logging.info(f"  Reached limit of {args.limit} items, stopping.")
                        break

                    # Random delay between items
                    delay = random.uniform(args.min_delay, args.max_delay)
                    time.sleep(delay)

            pbar_sets.update(1)

    # Get final statistics from database
    final_stats = get_statistics(conn)

    logging.info("\n" + "=" * 70)
    logging.info("Complete!")
    logging.info(f"  Items completed: {final_stats['completed_items']}")
    logging.info(f"  Items with errors: {final_stats['error_items']}")
    logging.info(f"  Files downloaded: {final_stats['downloaded_files']}")
    logging.info(f"  Files already existed: {final_stats['existing_files']}")
    logging.info(f"  Total errors logged: {final_stats['error_count']}")
    logging.info(f"  Database: {db_path}")
    logging.info(f"  Logs: {log_file}")
    logging.info("=" * 70)

    conn.close()

if __name__ == "__main__":
    main()