#!/usr/bin/env python3
"""
Reset extraction data - clears the extracted_service_data table

This script allows you to clear extraction records so you can re-run
the extraction process with updated prompts or models.
"""

import sqlite3
import sys
from pathlib import Path

# Configuration
DB_PATH = "usct_pension_files/pension_data.db"

def get_extraction_counts(conn):
    """Get current extraction statistics."""
    cursor = conn.execute("SELECT COUNT(*) FROM extracted_service_data")
    total = cursor.fetchone()[0]

    cursor = conn.execute("SELECT COUNT(*) FROM extracted_service_data WHERE status='completed'")
    completed = cursor.fetchone()[0]

    cursor = conn.execute("SELECT COUNT(*) FROM extracted_service_data WHERE status='error'")
    errors = cursor.fetchone()[0]

    return total, completed, errors

def reset_all_extractions(conn):
    """Delete all records from extracted_service_data table."""
    conn.execute("DELETE FROM extracted_service_data")
    conn.commit()
    print("All extraction records deleted.")

def reset_completed_only(conn):
    """Delete only completed extractions (keeps errors for review)."""
    cursor = conn.execute("SELECT COUNT(*) FROM extracted_service_data WHERE status='completed'")
    count = cursor.fetchone()[0]

    conn.execute("DELETE FROM extracted_service_data WHERE status='completed'")
    conn.commit()
    print(f"Deleted {count} completed extraction records (kept error records).")

def reset_errors_only(conn):
    """Delete only error records."""
    cursor = conn.execute("SELECT COUNT(*) FROM extracted_service_data WHERE status='error'")
    count = cursor.fetchone()[0]

    conn.execute("DELETE FROM extracted_service_data WHERE status='error'")
    conn.commit()
    print(f"Deleted {count} error extraction records (kept completed records).")

def reset_specific_items(conn, item_ids):
    """Delete extraction records for specific item IDs."""
    placeholders = ','.join('?' * len(item_ids))
    query = f"DELETE FROM extracted_service_data WHERE item_id IN ({placeholders})"
    conn.execute(query, item_ids)
    conn.commit()
    print(f"Deleted extraction records for {len(item_ids)} items.")

def main():
    """Main execution function."""

    # Check if database exists
    db_path = Path(DB_PATH)
    if not db_path.exists():
        print(f"ERROR: Database not found at {DB_PATH}")
        print("No extractions to reset.")
        return 1

    # Connect to database
    conn = sqlite3.connect(DB_PATH)

    # Get current counts
    total, completed, errors = get_extraction_counts(conn)

    if total == 0:
        print("No extraction records found in database.")
        conn.close()
        return 0

    # Display current status
    print("=" * 70)
    print("Current Extraction Status:")
    print(f"  Total records: {total}")
    print(f"  Completed: {completed}")
    print(f"  Errors: {errors}")
    print("=" * 70)

    # Get user choice
    print("\nWhat would you like to reset?")
    print("  1. Delete ALL extraction records")
    print("  2. Delete only COMPLETED extractions (keep errors)")
    print("  3. Delete only ERROR extractions (keep completed)")
    print("  4. Cancel (do nothing)")
    print()

    try:
        choice = input("Enter choice (1-4): ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        conn.close()
        return 0

    if choice == "1":
        confirm = input(f"\nAre you sure you want to delete ALL {total} extraction records? (yes/no): ").strip().lower()
        if confirm == "yes":
            reset_all_extractions(conn)
        else:
            print("Cancelled.")

    elif choice == "2":
        if completed == 0:
            print("No completed records to delete.")
        else:
            confirm = input(f"\nAre you sure you want to delete {completed} completed records? (yes/no): ").strip().lower()
            if confirm == "yes":
                reset_completed_only(conn)
            else:
                print("Cancelled.")

    elif choice == "3":
        if errors == 0:
            print("No error records to delete.")
        else:
            confirm = input(f"\nAre you sure you want to delete {errors} error records? (yes/no): ").strip().lower()
            if confirm == "yes":
                reset_errors_only(conn)
            else:
                print("Cancelled.")

    elif choice == "4":
        print("Cancelled.")

    else:
        print("Invalid choice. Cancelled.")

    # Show final counts
    total_after, completed_after, errors_after = get_extraction_counts(conn)

    if total_after != total:
        print("\n" + "=" * 70)
        print("Final Status:")
        print(f"  Total records: {total_after}")
        print(f"  Completed: {completed_after}")
        print(f"  Errors: {errors_after}")
        print("=" * 70)

    conn.close()
    return 0

if __name__ == "__main__":
    try:
        exit(main())
    except KeyboardInterrupt:
        print("\nCancelled.")
        exit(0)
