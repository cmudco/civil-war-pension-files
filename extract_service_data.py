#!/usr/bin/env python3
"""
Extract military service data from USCT pension file descriptions using OpenAI Structured Outputs.

This script processes pension file metadata stored in the database and extracts structured
military service information using GPT models with structured output capabilities.
"""

import sqlite3
import json
import logging
import time
import os
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, Tuple, List

import openai
from openai import OpenAI
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from tqdm import tqdm

# ============================================================================
# CONFIGURATION
# ============================================================================

# Database settings
DB_PATH = "usct_pension_files/pension_data.db"
LOG_FILE = "extraction.log"

# OpenAI settings
OPENAI_MODEL = "gpt-5-nano"  # Cost: $0.05/$0.40 per 1M tokens

# Batch processing settings
BATCH_LIMIT = 100  # Process up to N unprocessed records (None for all)
RETRY_ERRORS = True  # Whether to retry previously failed extractions

# API settings
REQUEST_TIMEOUT = 60  # Timeout for API requests in seconds
MAX_RETRIES = 3  # Maximum retry attempts for failed API calls
RETRY_DELAY = 2.0  # Base delay between retries (exponential backoff)

# ============================================================================
# PYDANTIC MODEL FOR STRUCTURED OUTPUTS
# ============================================================================

class MilitaryServiceData(BaseModel):
    """
    Structured military service information extracted from Civil War pension files.
    All fields are optional as not all information may be present in every record.
    """

    regiment: Optional[str] = Field(
        None,
        description="Regiment name (e.g., '34th United States Colored Troops', '55th Massachusetts Volunteer Infantry'). May include multiple regiments separated by semicolons."
    )

    company: Optional[str] = Field(
        None,
        description="Company designation (e.g., 'A', 'C or D', 'E; F'). May be a letter or range."
    )

    rank: Optional[str] = Field(
        None,
        description="Military rank (e.g., 'Private', 'Sergeant', 'Corporal'). May include multiple ranks if promoted."
    )

    mustered_in_date_place: Optional[str] = Field(
        None,
        description="Date and place where soldier mustered in or enrolled. Extract complete information including date and location."
    )

    mustered_out_date_place: Optional[str] = Field(
        None,
        description="Date and place where soldier mustered out or was discharged. Extract complete information."
    )

    other_locations: Optional[str] = Field(
        None,
        description="Other locations listed during time of service"
    )

    comrades: Optional[str] = Field(
        None,
        description="Comrades mentioned"
    )

    spouse_names: Optional[str] = Field(
        None,
        description="Name(s) of spouse(s)"
    )

    children: Optional[str] = Field(
        None,
        description="Children"
    )

    veteran_birth: Optional[str] = Field(
        None,
        description="Veteran's birth date and place"
    )

    plantation: Optional[str] = Field(
        None,
        description="Plantation"
    )

    enslaver: Optional[str] = Field(
        None,
        description="Enslaver"
    )

    parents: Optional[str] = Field(
        None,
        description="Parents of veteran"
    )

    other_family: Optional[str] = Field(
        None,
        description="Other listed family members"
    )

    wife_birth_place: Optional[str] = Field(
        None,
        description="Wife's place of birth"
    )

    wife_enslaver: Optional[str] = Field(
        None,
        description="Wife's enslaver"
    )

    wife_parents: Optional[str] = Field(
        None,
        description="Wife's parents"
    )

    wife_other_family: Optional[str] = Field(
        None,
        description="Wife's other family members"
    )

# ============================================================================
# DATABASE FUNCTIONS
# ============================================================================

def init_extraction_table(conn):
    """Initialize the extracted_service_data table if it doesn't exist."""

    # Create table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS extracted_service_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,

            -- Military Service Fields (18 total)
            regiment TEXT,
            company TEXT,
            rank TEXT,
            mustered_in_date_place TEXT,
            mustered_out_date_place TEXT,
            other_locations TEXT,
            comrades TEXT,
            spouse_names TEXT,
            children TEXT,
            veteran_birth TEXT,
            plantation TEXT,
            enslaver TEXT,
            parents TEXT,
            other_family TEXT,
            wife_birth_place TEXT,
            wife_enslaver TEXT,
            wife_parents TEXT,
            wife_other_family TEXT,

            -- Processing metadata
            raw_description TEXT,
            extraction_model TEXT,
            extraction_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processing_time_ms INTEGER,
            input_tokens INTEGER,
            output_tokens INTEGER,
            extraction_cost REAL,
            status TEXT DEFAULT 'pending',
            error_message TEXT,

            FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE,
            UNIQUE(item_id)
        )
    """)

    # Create indexes
    conn.execute("CREATE INDEX IF NOT EXISTS idx_extracted_status ON extracted_service_data(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_extracted_item_id ON extracted_service_data(item_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_extracted_date ON extracted_service_data(extraction_date DESC)")

    # Add new columns if they don't exist (for existing tables)
    cursor = conn.execute("PRAGMA table_info(extracted_service_data)")
    existing_columns = {row[1] for row in cursor.fetchall()}

    if 'input_tokens' not in existing_columns:
        conn.execute("ALTER TABLE extracted_service_data ADD COLUMN input_tokens INTEGER")
        logging.info("Added input_tokens column")

    if 'output_tokens' not in existing_columns:
        conn.execute("ALTER TABLE extracted_service_data ADD COLUMN output_tokens INTEGER")
        logging.info("Added output_tokens column")

    if 'extraction_cost' not in existing_columns:
        conn.execute("ALTER TABLE extracted_service_data ADD COLUMN extraction_cost REAL")
        logging.info("Added extraction_cost column")

    conn.commit()
    logging.info("Extraction table initialized")

def get_unprocessed_items(conn, limit=None, retry_errors=False):
    """
    Get items that need service data extraction.

    Args:
        conn: Database connection
        limit: Maximum number of items to return (None for all)
        retry_errors: If True, include items with previous extraction errors

    Returns:
        List of (item_id, dc_description) tuples
    """

    # Build status filter
    if retry_errors:
        status_filter = "AND (es.id IS NULL OR es.status = 'error')"
    else:
        status_filter = "AND es.id IS NULL"

    # Build query - get full metadata JSON
    query = f"""
        SELECT
            i.id,
            i.metadata
        FROM items i
        LEFT JOIN extracted_service_data es ON i.id = es.item_id
        WHERE
            i.status = 'completed'
            {status_filter}
        ORDER BY i.id
    """

    if limit:
        query += f" LIMIT {limit}"

    cursor = conn.execute(query)
    rows = cursor.fetchall()

    # Extract dc_description from metadata JSON
    results = []
    for item_id, metadata_json in rows:
        try:
            metadata = json.loads(metadata_json)
            dc_desc = metadata.get('dc_description', [])

            # Join ALL array elements into one complete description
            if isinstance(dc_desc, list) and len(dc_desc) > 0:
                # Join all elements with newlines
                description = '\n'.join(str(elem) for elem in dc_desc if elem)
            elif isinstance(dc_desc, str):
                description = dc_desc
            else:
                description = None

            # Only include if we have a description
            if description and description.strip():
                results.append((item_id, description))
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logging.warning(f"Failed to extract description for item {item_id}: {e}")
            continue

    return results

def record_extraction(conn, item_id, extracted_data, model_name,
                     processing_time_ms, raw_description, input_tokens=None,
                     output_tokens=None, extraction_cost=None, status='completed',
                     error_message=None):
    """Record extraction results in database."""

    # Convert Pydantic model to dict, handling None values
    if extracted_data:
        data_dict = extracted_data.model_dump()
    else:
        data_dict = {field: None for field in MilitaryServiceData.model_fields.keys()}

    # Check if record exists
    cursor = conn.execute(
        "SELECT id FROM extracted_service_data WHERE item_id = ?",
        (item_id,)
    )
    existing = cursor.fetchone()

    if existing:
        # Update existing record
        conn.execute("""
            UPDATE extracted_service_data
            SET
                regiment = ?,
                company = ?,
                rank = ?,
                mustered_in_date_place = ?,
                mustered_out_date_place = ?,
                other_locations = ?,
                comrades = ?,
                spouse_names = ?,
                children = ?,
                veteran_birth = ?,
                plantation = ?,
                enslaver = ?,
                parents = ?,
                other_family = ?,
                wife_birth_place = ?,
                wife_enslaver = ?,
                wife_parents = ?,
                wife_other_family = ?,
                raw_description = ?,
                extraction_model = ?,
                extraction_date = CURRENT_TIMESTAMP,
                processing_time_ms = ?,
                input_tokens = ?,
                output_tokens = ?,
                extraction_cost = ?,
                status = ?,
                error_message = ?
            WHERE item_id = ?
        """, (
            data_dict['regiment'],
            data_dict['company'],
            data_dict['rank'],
            data_dict['mustered_in_date_place'],
            data_dict['mustered_out_date_place'],
            data_dict['other_locations'],
            data_dict['comrades'],
            data_dict['spouse_names'],
            data_dict['children'],
            data_dict['veteran_birth'],
            data_dict['plantation'],
            data_dict['enslaver'],
            data_dict['parents'],
            data_dict['other_family'],
            data_dict['wife_birth_place'],
            data_dict['wife_enslaver'],
            data_dict['wife_parents'],
            data_dict['wife_other_family'],
            raw_description,
            model_name,
            processing_time_ms,
            input_tokens,
            output_tokens,
            extraction_cost,
            status,
            error_message,
            item_id
        ))
    else:
        # Insert new record
        conn.execute("""
            INSERT INTO extracted_service_data (
                item_id, regiment, company, rank,
                mustered_in_date_place, mustered_out_date_place,
                other_locations, comrades, spouse_names, children,
                veteran_birth, plantation, enslaver, parents,
                other_family, wife_birth_place, wife_enslaver,
                wife_parents, wife_other_family,
                raw_description, extraction_model, processing_time_ms,
                input_tokens, output_tokens, extraction_cost,
                status, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            item_id,
            data_dict['regiment'],
            data_dict['company'],
            data_dict['rank'],
            data_dict['mustered_in_date_place'],
            data_dict['mustered_out_date_place'],
            data_dict['other_locations'],
            data_dict['comrades'],
            data_dict['spouse_names'],
            data_dict['children'],
            data_dict['veteran_birth'],
            data_dict['plantation'],
            data_dict['enslaver'],
            data_dict['parents'],
            data_dict['other_family'],
            data_dict['wife_birth_place'],
            data_dict['wife_enslaver'],
            data_dict['wife_parents'],
            data_dict['wife_other_family'],
            raw_description,
            model_name,
            processing_time_ms,
            input_tokens,
            output_tokens,
            extraction_cost,
            status,
            error_message
        ))

    conn.commit()

def get_extraction_statistics(conn):
    """Get statistics about extraction progress."""
    stats = {}

    cursor = conn.execute("SELECT COUNT(*) FROM extracted_service_data WHERE status='completed'")
    stats['completed'] = cursor.fetchone()[0]

    cursor = conn.execute("SELECT COUNT(*) FROM extracted_service_data WHERE status='error'")
    stats['error'] = cursor.fetchone()[0]

    cursor = conn.execute("""
        SELECT COUNT(*) FROM items i
        LEFT JOIN extracted_service_data es ON i.id = es.item_id
        WHERE i.status = 'completed'
        AND json_extract(i.metadata, '$.dc_description[0]') IS NOT NULL
        AND es.id IS NULL
    """)
    stats['pending'] = cursor.fetchone()[0]

    return stats

# ============================================================================
# OPENAI EXTRACTION
# ============================================================================

def extract_service_data(client, description_text, model=OPENAI_MODEL):
    """
    Extract military service data using OpenAI Structured Outputs.

    Args:
        client: OpenAI client instance
        description_text: Raw dc_description text to parse
        model: OpenAI model to use

    Returns:
        Tuple of (MilitaryServiceData, processing_time_ms, input_tokens, output_tokens, cost)

    Raises:
        openai.APIError: If API call fails after retries
    """

    start_time = time.time()

    system_prompt = "Extract military service data from Civil War pension file descriptions. Extract field values exactly as written. If a field says 'Not listed', extract 'Not listed'."

    user_prompt = f"Extract the military service data from this description:\n\n{description_text}"

    # Print debug information
    print("\n" + "=" * 80)
    print("API REQUEST DEBUG")
    print("=" * 80)
    print(f"Model: {model}")
    print(f"\nSystem Prompt:\n{system_prompt}")
    print(f"\nUser Prompt:\n{user_prompt}")
    print("=" * 80)

    try:
        # Create chat completion with structured output
        completion = client.beta.chat.completions.parse(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": user_prompt
                }
            ],
            response_format=MilitaryServiceData,
            timeout=REQUEST_TIMEOUT
        )

        processing_time_ms = int((time.time() - start_time) * 1000)

        # Extract the parsed data
        extracted_data = completion.choices[0].message.parsed

        # Get token usage
        usage = completion.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0

        # Calculate cost based on model pricing
        # gpt-5-nano: $0.05 per 1M input tokens, $0.40 per 1M output tokens
        input_cost = (input_tokens / 1_000_000) * 0.05
        output_cost = (output_tokens / 1_000_000) * 0.40
        total_cost = input_cost + output_cost

        # Print response debug information
        print("\n" + "=" * 80)
        print("API RESPONSE DEBUG")
        print("=" * 80)
        print(f"Processing time: {processing_time_ms}ms")
        print(f"\nToken Usage:")
        print(f"  Input tokens: {input_tokens:,}")
        print(f"  Output tokens: {output_tokens:,}")
        print(f"  Total tokens: {input_tokens + output_tokens:,}")
        print(f"\nCost Breakdown:")
        print(f"  Input cost:  ${input_cost:.6f}")
        print(f"  Output cost: ${output_cost:.6f}")
        print(f"  Total cost:  ${total_cost:.6f}")
        print(f"\nExtracted Data:")

        # Print all fields
        data_dict = extracted_data.model_dump()
        for field_name, field_value in data_dict.items():
            status = "✓" if field_value else "✗"
            print(f"  {status} {field_name}: {repr(field_value)}")

        print("=" * 80)
        print()

        return extracted_data, processing_time_ms, input_tokens, output_tokens, total_cost

    except openai.APIError as e:
        processing_time_ms = int((time.time() - start_time) * 1000)
        print(f"\nAPI ERROR: {e}")
        logging.error(f"OpenAI API error: {e}")
        raise

# ============================================================================
# MAIN PROCESSING LOOP
# ============================================================================

def process_batch(conn, client, batch_limit=None, retry_errors=False):
    """
    Process a batch of unprocessed items with progress tracking.

    Args:
        conn: Database connection
        client: OpenAI client
        batch_limit: Maximum number of items to process
        retry_errors: Whether to retry previously failed items
    """

    # Get items to process
    items_to_process = get_unprocessed_items(conn, batch_limit, retry_errors)

    if not items_to_process:
        logging.info("No items to process")
        return

    logging.info(f"Processing {len(items_to_process)} items...")

    success_count = 0
    error_count = 0
    total_processing_time_ms = 0

    # Process with progress bar
    with tqdm(total=len(items_to_process), desc="Extracting service data") as pbar:
        for item_id, description in items_to_process:

            if not description:
                logging.warning(f"Item {item_id} has no description, skipping")
                pbar.update(1)
                continue

            # Attempt extraction with retries
            for attempt in range(MAX_RETRIES):
                try:
                    extracted_data, processing_time_ms, input_tokens, output_tokens, cost = extract_service_data(
                        client,
                        description,
                        OPENAI_MODEL
                    )

                    # Record success
                    record_extraction(
                        conn,
                        item_id,
                        extracted_data,
                        OPENAI_MODEL,
                        processing_time_ms,
                        description,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        extraction_cost=cost,
                        status='completed'
                    )

                    success_count += 1
                    total_processing_time_ms += processing_time_ms
                    pbar.set_postfix_str(f"✓ {success_count} | ✗ {error_count}")
                    break

                except openai.APIError as e:
                    if attempt < MAX_RETRIES - 1:
                        # Retry with exponential backoff
                        delay = RETRY_DELAY * (2 ** attempt)
                        logging.warning(f"API error for item {item_id}, retrying in {delay}s...")
                        time.sleep(delay)
                    else:
                        # Final attempt failed
                        error_msg = str(e)
                        logging.error(f"Failed to extract item {item_id} after {MAX_RETRIES} attempts: {error_msg}")

                        record_extraction(
                            conn,
                            item_id,
                            None,
                            OPENAI_MODEL,
                            0,
                            description,
                            input_tokens=None,
                            output_tokens=None,
                            extraction_cost=None,
                            status='error',
                            error_message=error_msg
                        )

                        error_count += 1
                        pbar.set_postfix_str(f"✓ {success_count} | ✗ {error_count}")

                except Exception as e:
                    error_msg = str(e)
                    logging.error(f"Unexpected error for item {item_id}: {error_msg}")

                    record_extraction(
                        conn,
                        item_id,
                        None,
                        OPENAI_MODEL,
                        0,
                        description,
                        input_tokens=None,
                        output_tokens=None,
                        extraction_cost=None,
                        status='error',
                        error_message=error_msg
                    )

                    error_count += 1
                    pbar.set_postfix_str(f"✓ {success_count} | ✗ {error_count}")
                    break

            pbar.update(1)

    # Print summary
    avg_time = total_processing_time_ms / success_count if success_count > 0 else 0
    logging.info(f"\nExtraction complete:")
    logging.info(f"  Success: {success_count}")
    logging.info(f"  Errors: {error_count}")
    logging.info(f"  Average processing time: {avg_time:.0f}ms")

# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    """Main execution function."""

    # Load environment variables
    load_dotenv()
    openai_api_key = os.getenv("OPENAI_API_KEY")

    if not openai_api_key:
        print("ERROR: OPENAI_API_KEY not found in environment variables")
        print("Please set it in your .env file")
        return 1

    # Setup logging
    output_path = Path("usct_pension_files")
    output_path.mkdir(exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] %(levelname)s: %(message)s',
        handlers=[
            logging.FileHandler(output_path / LOG_FILE, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )

    logging.info("=" * 70)
    logging.info("Military Service Data Extraction")
    logging.info(f"Model: {OPENAI_MODEL}")
    logging.info(f"Batch limit: {BATCH_LIMIT if BATCH_LIMIT else 'All'}")
    logging.info(f"Retry errors: {RETRY_ERRORS}")
    logging.info("=" * 70)

    # Initialize OpenAI client
    client = OpenAI(api_key=openai_api_key)

    # Connect to database
    db_path = output_path / DB_PATH.split('/')[-1]
    logging.info(f"Connecting to database: {db_path}")
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL")

    # Initialize extraction table
    init_extraction_table(conn)

    # Get initial statistics
    stats_before = get_extraction_statistics(conn)
    logging.info(f"Initial status: {stats_before['completed']} completed, {stats_before['error']} errors, {stats_before['pending']} pending")

    # Process batch
    process_batch(conn, client, BATCH_LIMIT, RETRY_ERRORS)

    # Get final statistics
    stats_after = get_extraction_statistics(conn)
    logging.info("\n" + "=" * 70)
    logging.info("Extraction Summary:")
    logging.info(f"  Completed: {stats_after['completed']} (was {stats_before['completed']})")
    logging.info(f"  Errors: {stats_after['error']} (was {stats_before['error']})")
    logging.info(f"  Pending: {stats_after['pending']} (was {stats_before['pending']})")
    logging.info("=" * 70)

    conn.close()
    return 0

if __name__ == "__main__":
    exit(main())
