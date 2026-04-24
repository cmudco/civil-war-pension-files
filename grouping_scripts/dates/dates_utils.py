import sqlite3
import pandas as pd

from utils.clean_utils import standardize_nulls
from utils.db_utils import ensure_column

def load_dates_from_db(db_path, custom_where=""):
    """Load and normalize raw date records from the database."""
    print("Loading raw dates from database...")
    
    # Ensure cluster_id exists for consistency
    ensure_column(db_path, "dates", "cluster_id")
    
    conn = sqlite3.connect(db_path)

    query = f"""
        SELECT 
            id, pdf_file, page, 
            month, day, year, date_type, context 
        FROM dates
        {custom_where}
    """
    df = pd.read_sql_query(query, conn)
    conn.close()

    if df.empty:
        return df

    date_cols = ['month', 'day', 'year', 'date_type', 'context']
    df = standardize_nulls(df, date_cols)

    return df

