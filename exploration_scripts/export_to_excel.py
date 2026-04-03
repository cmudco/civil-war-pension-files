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

    # Read items table with extracted service data
    print("Reading items table with extracted service data...")
    query = """
        SELECT
            i.*,
            es.regiment as extracted_regiment,
            es.company as extracted_company,
            es.rank as extracted_rank,
            es.mustered_in_date_place as extracted_mustered_in,
            es.mustered_out_date_place as extracted_mustered_out,
            es.other_locations as extracted_locations,
            es.comrades as extracted_comrades,
            es.spouse_names as extracted_spouses,
            es.children as extracted_children,
            es.veteran_birth as extracted_vet_birth,
            es.plantation as extracted_plantation,
            es.enslaver as extracted_enslaver,
            es.parents as extracted_parents,
            es.other_family as extracted_other_family,
            es.wife_birth_place as extracted_wife_birth,
            es.wife_enslaver as extracted_wife_enslaver,
            es.wife_parents as extracted_wife_parents,
            es.wife_other_family as extracted_wife_other_family,
            es.extraction_model as extraction_model,
            es.extraction_date as extraction_date,
            es.input_tokens as extraction_input_tokens,
            es.output_tokens as extraction_output_tokens,
            es.extraction_cost as extraction_cost,
            es.status as extraction_status,
            es.error_message as extraction_error
        FROM items i
        LEFT JOIN extracted_service_data es ON i.id = es.item_id
    """
    df = pd.read_sql_query(query, conn)
    print(f"Found {len(df)} items")

    # Count how many have extractions
    extracted_count = df['extraction_status'].notna().sum()
    print(f"  {extracted_count} items have extracted service data")
    if extracted_count > 0:
        completed_count = (df['extraction_status'] == 'completed').sum()
        error_count = (df['extraction_status'] == 'error').sum()
        print(f"  {completed_count} successful extractions, {error_count} with errors")

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

    # Show extracted service data statistics
    if extracted_count > 0:
        print("\nExtracted service data columns:")
        extracted_cols = [col for col in df_export.columns if col.startswith('extracted_')]
        for col in extracted_cols:
            non_null = df_export[col].notna().sum()
            print(f"  - {col}: {non_null} non-null values")

        # Show cost statistics
        total_cost = df_export['extraction_cost'].sum()
        avg_cost = df_export['extraction_cost'].mean()
        total_input_tokens = df_export['extraction_input_tokens'].sum()
        total_output_tokens = df_export['extraction_output_tokens'].sum()

        print(f"\nCost Statistics:")
        print(f"  - Total extractions: {completed_count}")
        print(f"  - Total cost: ${total_cost:.4f}")
        print(f"  - Average cost per extraction: ${avg_cost:.6f}")
        print(f"  - Total input tokens: {int(total_input_tokens):,}")
        print(f"  - Total output tokens: {int(total_output_tokens):,}")

    print("\nColumn organization:")
    print("  - Original: id, title, surname, item_set_id, letter_range, status, etc.")
    print("  - Metadata (meta_*): dc_description, dc_date, dc_coverage, etc.")
    if extracted_count > 0:
        print("  - Extracted (extracted_*): regiment, company, rank, mustered_in, etc.")
        print("  - Extraction metadata: model, date, tokens, cost, status")
    else:
        print("  - No extracted service data yet (run extract_service_data.py first)")
    print("="*70)

    conn.close()

if __name__ == "__main__":
    export_to_excel()
