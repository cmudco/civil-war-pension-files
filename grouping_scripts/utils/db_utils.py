import sqlite3


def ensure_column(db_path, table, column, col_type="TEXT"):
    """Add a column to a table if it doesn't already exist."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists
    finally:
        conn.close()


def update_cluster_ids(db_path, table, id_col, cluster_col, df):
    """Write cluster IDs from a DataFrame back to a database table.
    
    Args:
        db_path: Path to the SQLite database.
        table: Table name to update.
        id_col: DataFrame column containing the row ID.
        cluster_col: DataFrame column containing the cluster ID.
        df: DataFrame with the cluster assignments.
    """
    if df is None or df.empty:
        print("No data to update.")
        return

    ensure_column(db_path, table, "cluster_id")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        updates = list(df[[cluster_col, id_col]].itertuples(index=False, name=None))
        cursor.executemany(f"UPDATE {table} SET cluster_id = ? WHERE id = ?", updates)
        conn.commit()
        print(f"Successfully updated {len(updates)} records in the {table} table.")
    except sqlite3.Error as e:
        print(f"Database error: {e}")
    finally:
        conn.close()
