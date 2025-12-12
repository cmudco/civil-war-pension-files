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
from pathlib import Path

# Configuration
BASE_URL = "https://iaamcfh.omeka.net"
API_BASE = f"{BASE_URL}/api"
OUTPUT_DIR = "usct_pension_files"
METADATA_FILE = "pension_metadata.json"
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

def api_get(endpoint, params=None):
    """Make API request with retry logic."""
    url = f"{API_BASE}/{endpoint}"
    for attempt in range(3):
        try:
            resp = session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    return None

def get_items_in_set(item_set_id, per_page=100):
    """Fetch all items from an item set via API."""
    items = []
    page = 1
    
    while True:
        params = {"item_set_id": item_set_id, "per_page": per_page, "page": page}
        data = api_get("items", params)
        
        if not data:
            break
            
        items.extend(data)
        print(f"    Page {page}: {len(data)} items")
        
        if len(data) < per_page:
            break
        page += 1
        time.sleep(0.3)
    
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

def process_item(item, set_dir):
    """Process a single item: extract metadata and download files."""
    item_id = item.get("o:id")
    title = item.get("o:title", f"item_{item_id}")
    metadata = extract_metadata(item)
    metadata["files"] = []
    
    # Process each media file
    for media_id in metadata["media_ids"]:
        try:
            media = get_media_details(media_id)
            if not media:
                continue
            
            # Get the original file URL
            original_url = media.get("o:original_url")
            if not original_url:
                continue
            
            # Get filename info - prefer o:source (original upload name)
            source_filename = media.get("o:source", "")  # e.g., "Brown Isaiah Civil War Pension.pdf"
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
            
            # Download if needed
            if not filepath.exists():
                size = download_file(original_url, filepath)
                status = f"downloaded ({size // 1024} KB)"
            else:
                size = filepath.stat().st_size
                status = "exists"
            
            metadata["files"].append({
                "media_id": media_id,
                "filename": local_filename,
                "source_filename": source_filename,
                "url": original_url,
                "media_type": media_type,
                "size": file_size,
                "sha256": media.get("o:sha256"),
                "status": status
            })
            
        except Exception as e:
            metadata["files"].append({
                "media_id": media_id,
                "error": str(e)
            })
    
    return metadata

def main():
    parser = argparse.ArgumentParser(description="Download USCT pension files from IAAM")
    parser.add_argument("--limit", type=int, default=None, help="Max items to download (for testing)")
    parser.add_argument("--set", type=str, default=None, help="Only process this letter range (e.g., 'A-B')")
    args = parser.parse_args()
    
    output_path = Path(OUTPUT_DIR)
    output_path.mkdir(exist_ok=True)
    
    all_metadata = []
    stats = {"items": 0, "files": 0, "downloaded": 0, "errors": 0}
    total_processed = 0
    
    print("=" * 70)
    print("IAAM USCT Pension Files Downloader")
    if args.limit:
        print(f"  TEST MODE: Limiting to {args.limit} item(s)")
    if args.set:
        print(f"  Filtering to set: {args.set}")
    print("=" * 70)
    
    for item_set_id, letter_range in ITEM_SET_IDS.items():
        # Skip if user specified a different set
        if args.set and letter_range != args.set:
            continue
        
        # Stop if we've hit the limit
        if args.limit and total_processed >= args.limit:
            break
        print(f"\n[{letter_range}] Fetching item set {item_set_id}...")
        
        set_dir = output_path / letter_range.replace("-", "_")
        set_dir.mkdir(exist_ok=True)
        
        items = get_items_in_set(item_set_id)
        print(f"  Found {len(items)} items in {letter_range}")
        
        for i, item in enumerate(items, 1):
            # Check limit
            if args.limit and total_processed >= args.limit:
                print(f"  Reached limit of {args.limit} items, stopping.")
                break
            
            title = item.get("o:title", "Unknown")[:40]
            print(f"  [{i:3d}/{len(items)}] {title}...", end=" ", flush=True)
            
            try:
                metadata = process_item(item, set_dir)
                all_metadata.append(metadata)
                stats["items"] += 1
                
                # Count files
                for f in metadata["files"]:
                    if "error" in f:
                        stats["errors"] += 1
                        print("✗", end="")
                    else:
                        stats["files"] += 1
                        if f["status"].startswith("downloaded"):
                            stats["downloaded"] += 1
                            print("↓", end="")
                        else:
                            print("✓", end="")
                
                print()
                
            except Exception as e:
                print(f"ERROR: {e}")
                stats["errors"] += 1
            
            total_processed += 1
            time.sleep(0.2)  # Rate limiting
    
    # Save metadata
    metadata_path = output_path / METADATA_FILE
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(all_metadata, f, indent=2, ensure_ascii=False)
    
    # Also save as CSV for easier analysis
    csv_path = output_path / "pension_index.csv"
    with open(csv_path, 'w', encoding='utf-8') as f:
        f.write("id,title,surname,date,regiment_info,files,locations\n")
        for m in all_metadata:
            desc = "; ".join(m.get("dc_description", [])[:1])  # First description
            files = "; ".join([fi.get("filename", "") for fi in m.get("files", [])])
            locs = "; ".join([loc.get("label", "") for loc in m.get("locations", [])])
            row = [
                str(m.get("id", "")),
                f'"{m.get("title", "")}"',
                f'"{"; ".join(m.get("surname", []))}"',
                f'"{"; ".join(m.get("dc_date", []))}"',
                f'"{desc[:200]}"',
                f'"{files}"',
                f'"{locs}"'
            ]
            f.write(",".join(row) + "\n")
    
    print("\n" + "=" * 70)
    print("Complete!")
    print(f"  Items processed: {stats['items']}")
    print(f"  Files found: {stats['files']}")
    print(f"  New downloads: {stats['downloaded']}")
    print(f"  Errors: {stats['errors']}")
    print(f"  Metadata: {metadata_path}")
    print(f"  CSV index: {csv_path}")
    print("=" * 70)

if __name__ == "__main__":
    main()