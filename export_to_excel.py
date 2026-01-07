#!/usr/bin/env python3
"""
Export pension_data.db items table to Excel
Extracts metadata JSON fields into separate columns
"""

import sqlite3
import json
import pandas as pd
from pathlib import Path

# ============================================================================
# CONFIGURATION
# ============================================================================
DB_PATH = "usct_pension_files/pension_data.db"
OUTPUT_FILE = "pension_data_export.xlsx"

# Fields to extract from the metadata JSON
METADATA_FIELDS = [
    "dc_description",
    "dc_date",
    "dc_coverage",
    "created",
    "dc_creator",
    "dc_publisher",
    "dc_rights",
    "dc_title",
    "id",
    "surname",
    "title"
]

# ============================================================================

def merge_list_to_string(value, separator="; "):
    """Convert list to string, handle various input types"""
    if value is None:
        return ""
    if isinstance(value, list):
        # Filter out None values and convert to strings
        return separator.join(str(item) for item in value if item is not None)
    return str(value)

def extract_metadata_fields(metadata_json):
    """Parse metadata JSON and extract specified fields"""
    result = {}

    try:
        metadata = json.loads(metadata_json) if isinstance(metadata_json, str) else metadata_json
    except (json.JSONDecodeError, TypeError):
        metadata = {}

    # Extract each field
    for field in METADATA_FIELDS:
        value = metadata.get(field)

        # Convert lists to strings
        if isinstance(value, list):
            result[field] = merge_list_to_string(value)
        elif value is None:
            result[field] = ""
        else:
            result[field] = str(value)

    return result

def export_to_excel():
    """Main export function"""
    print(f"Connecting to database: {DB_PATH}")

    # Check if database exists
    db_path = Path(DB_PATH)
    if not db_path.exists():
        print(f"ERROR: Database not found at {DB_PATH}")
        return

    # Connect to database
    conn = sqlite3.connect(DB_PATH)

    # Read items table
    print("Reading items table...")
    query = "SELECT * FROM items"
    df = pd.read_sql_query(query, conn)
    print(f"Found {len(df)} items")

    # Extract metadata fields into separate columns
    print("Extracting metadata fields...")
    metadata_df = df['metadata'].apply(extract_metadata_fields).apply(pd.Series)

    # Rename columns to add 'meta_' prefix to avoid conflicts
    metadata_df = metadata_df.add_prefix('meta_')

    # Combine original columns with extracted metadata
    # Drop the original metadata column to avoid clutter
    df_export = df.drop('metadata', axis=1)
    df_export = pd.concat([df_export, metadata_df], axis=1)

    # Write to Excel
    print(f"Writing to Excel: {OUTPUT_FILE}")
    df_export.to_excel(OUTPUT_FILE, index=False, engine='openpyxl')

    # Print summary
    print("\n" + "="*70)
    print("Export complete!")
    print(f"  Output file: {OUTPUT_FILE}")
    print(f"  Total rows: {len(df_export)}")
    print(f"  Total columns: {len(df_export.columns)}")
    print("\nColumns included:")
    for col in df_export.columns:
        print(f"  - {col}")
    print("="*70)

    conn.close()

if __name__ == "__main__":
    export_to_excel()
