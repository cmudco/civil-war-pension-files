import sqlite3
import pandas as pd

from utils.db_utils import ensure_column


def determine_role(text):
    """Scores text to categorize the person as primary, dependent, or unknown."""
    if pd.isna(text) or not str(text).strip():
        return 'unknown'

    text_lower = str(text).lower()
    if 'attorney' in text_lower:
        return 'primary'

    primary_words = ['soldier', 'private', 'pvt', 'corporal', 'father', 'parent', 'husband', 'co.', 'regt']
    primary_score = sum(text_lower.count(w) for w in primary_words)

    dependent_words = ['child', 'minor', 'daughter', 'son', 'widow', 'wife', 'guardian', 'orphan']
    dep_score = sum(text_lower.count(w) for w in dependent_words)

    if dep_score > primary_score:
        return 'dependent'
    elif primary_score > dep_score:
        return 'primary'
    else:
        return 'unknown'


def load_persons_from_db(db_path, custom_where_clause=""):
    """Loads and aggressively normalizes names from the database."""
    # Ensure the column exists so our SQL queries don't crash on a fresh database
    ensure_column(db_path, "persons", "cluster_id")
    ensure_column(db_path, "persons", "global_cluster_id")
    ensure_column(db_path, "persons", "gemini_extracted")
    ensure_column(db_path, "persons", "birth_age")
    ensure_column(db_path, "persons", "slaveholder_info")
    ensure_column(db_path, "persons", "marriage_info")
    ensure_column(db_path, "persons", "family_members")

    conn = sqlite3.connect(db_path)
    # We made the WHERE clause dynamic so you can reuse this for any test
    query = f"""
    SELECT 
        p.id as unique_id, p.pdf_file, p.page as page_num,
        p.first_name, p.last_name, p.middle_name, p.middle_initial, 
        p.context, p.title
    FROM persons p
    {custom_where_clause}
    """
    df = pd.read_sql_query(query, conn)
    conn.close()

    if df.empty:
        return df

    df = df.replace('--', '')

    # --- MIDDLE INITIAL FALLBACK ---
    df['mid_name_clean'] = df['middle_name'].fillna('').astype(str).str.strip()
    df['mid_init_clean'] = df['middle_initial'].fillna('').astype(str).str.strip()

    df['effective_middle'] = df.apply(
        lambda x: x['mid_init_clean'] if x['mid_name_clean'] == '' else x['mid_name_clean'],
        axis=1
    )

    # --- AGGRESSIVE NORMALIZATION ---
    first_clean = df["first_name"].fillna("").astype(str).str.replace(r'\.', '', regex=True)
    mid_clean = df["effective_middle"].fillna("").astype(str).str.replace(r'\.', '', regex=True)
    last_clean = df["last_name"].fillna("").astype(str).str.replace(r'\.', '', regex=True)

    df["entity_value"] = (first_clean + " " + mid_clean + " " + last_clean).str.replace(r'\s+', ' ', regex=True).str.strip().str.title()

    df["first_name"] = first_clean.astype(str).str.replace(r'\s+', '', regex=True).str.title()
    df["middle_name"] = mid_clean.astype(str).str.strip().str.title()
    df["last_name"] = last_clean.astype(str).str.strip().str.title()

    # Prevent .split() from crashing if pdf_file is a SQL NULL
    df["file_id"] = df["pdf_file"].fillna("").astype(str).apply(lambda x: x.split('/')[-1] if x else "unknown")

    df = df.drop(columns=['mid_name_clean', 'mid_init_clean', 'effective_middle'])
    return df


def update_database_with_clusters(df, db_path):
    """Saves the final cluster IDs back to the database."""
    if df is None or df.empty:
        return

    ensure_column(db_path, "persons", "cluster_id")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    update_data = df[['cluster_id', 'unique_id']].values.tolist()

    try:
        cursor.executemany("UPDATE persons SET cluster_id = ? WHERE id = ?", update_data)
        conn.commit()
        print(f"  [DB] Updated {len(update_data):,} cluster IDs in persons table.")
    except sqlite3.Error as e:
        print(f"  [ERROR] Database: {e}")
    finally:
        conn.close()


def build_master_list(db_path):
    """Collapse clustered person rows into canonical master profiles."""
    print("  [LOAD] Building master list from clustered persons...")
    
    # Ensure columns exist before we SELECT them
    ensure_column(db_path, "persons", "cluster_id")
    ensure_column(db_path, "persons", "global_cluster_id")
    ensure_column(db_path, "persons", "gemini_extracted")
    ensure_column(db_path, "persons", "birth_age")
    ensure_column(db_path, "persons", "slaveholder_info")
    ensure_column(db_path, "persons", "marriage_info")
    ensure_column(db_path, "persons", "family_members")
    conn = sqlite3.connect(db_path)

    query = """
        SELECT cluster_id, first_name, last_name, pdf_file, gemini_extracted,
               birth_age, slaveholder_info, marriage_info, family_members
        FROM persons 
        WHERE cluster_id IS NOT NULL 
    """
    df = pd.read_sql_query(query, conn)
    conn.close()

    if df.empty:
        return pd.DataFrame()

    # Wipe out NaNs before they become literal "nan" strings
    df = df.fillna("")

    # Cleanly generate full names
    df["full_name"] = (df["first_name"].astype(str) + " " + df["last_name"].astype(str)).str.replace(r'\s+', ' ', regex=True).str.strip().str.title()

    # Collapse into Master Profiles
    master_records = []
    for c_id, group in df.groupby('cluster_id'):
        name_counts = group['full_name'].value_counts()

        # Ignore completely blank names when crowning the canonical name
        valid_names = [n for n in name_counts.index if str(n).strip() != ""]

        canonical = valid_names[0] if len(valid_names) > 0 else "Unknown Name"
        alt = valid_names[1] if len(valid_names) > 1 else canonical

        master_records.append({
            'cluster_id': c_id,
            'canonical_name': canonical,
            'alt_name': alt,
            'pdf_file': group['pdf_file'].iloc[0],
            'gemini_extracted': str(group['gemini_extracted'].iloc[0]).strip(),
            'birth_age': group['birth_age'].iloc[0],
            'slaveholder_info': group['slaveholder_info'].iloc[0],
            'marriage_info': group['marriage_info'].iloc[0],
            'family_members': group['family_members'].iloc[0]
        })

    master_df = pd.DataFrame(master_records)
    print(f"  [DONE] {len(df):,} rows -> {len(master_df):,} master profiles.")
    return master_df


def generate_global_master_csv(db_path, output_csv="GLOBAL_MASTER_EXTRACTED.csv"):
    """Export global identities to a clean summary CSV."""
    print("  [EXPORT] Writing global master CSV...")
    
    # Ensure columns exist before we SELECT them
    ensure_column(db_path, "persons", "global_cluster_id")
    ensure_column(db_path, "persons", "cluster_id")
    ensure_column(db_path, "persons", "gemini_extracted")
    ensure_column(db_path, "persons", "birth_age")
    ensure_column(db_path, "persons", "slaveholder_info")
    ensure_column(db_path, "persons", "marriage_info")
    ensure_column(db_path, "persons", "family_members")
    conn = sqlite3.connect(db_path)

    query = """
        SELECT global_cluster_id, cluster_id as local_cluster_id,
               first_name, last_name, pdf_file, gemini_extracted,
               birth_age, slaveholder_info, marriage_info, family_members
        FROM persons
        WHERE global_cluster_id IS NOT NULL
    """
    df = pd.read_sql_query(query, conn)
    conn.close()

    if df.empty:
        print("  [WARN] No global clusters found.")
        return

    df = df.fillna("")
    df["full_name"] = (df["first_name"].astype(str) + " " + df["last_name"].astype(str)).str.replace(r'\s+', ' ', regex=True).str.strip().str.title()

    global_records = []

    for g_id, group in df.groupby('global_cluster_id'):

        # --- 1. NAME RESOLUTION ---
        name_counts = group['full_name'].value_counts()
        valid_names = [n for n in name_counts.index if str(n).strip() != ""]

        primary_name = valid_names[0] if valid_names else "Unknown"
        aliases = " | ".join(valid_names[1:]) if len(valid_names) > 1 else ""

        # --- 2. FILE AGGREGATION ---
        unique_files = group['pdf_file'].unique()
        unique_files_clean = [str(f).split('\\')[-1].split('/')[-1] for f in unique_files if f]

        # --- 3. BIO AGGREGATION ---
        def agg_bio(col_name):
            vals = [str(v).strip() for v in group[col_name].unique() if str(v).strip() not in ("", "None", "null", "nan")]
            final_vals = []
            for v in vals:
                is_fragment = any(v in other and v != other for other in vals)
                if not is_fragment:
                    final_vals.append(v)
            return " | ".join(final_vals)

        global_records.append({
            'global_id': g_id,
            'primary_name': primary_name,
            'aliases': aliases,
            'linked_files_count': len(unique_files_clean),
            'source_files': " | ".join(unique_files_clean),
            'total_rows_merged': len(group),
            'ai_extracted': 'Yes' if any(group['gemini_extracted'].astype(str).str.strip().isin(['1', '1.0'])) else 'No',
            'birth_age': agg_bio('birth_age'),
            'slaveholder_info': agg_bio('slaveholder_info'),
            'marriage_info': agg_bio('marriage_info'),
            'family_members': agg_bio('family_members')
        })

    global_df = pd.DataFrame(global_records)

    # Only keep identities where at least one linked file was AI Extracted
    initial_count = len(global_df)
    global_df = global_df[global_df['ai_extracted'] == 'Yes']

    global_df = global_df.sort_values(by=['linked_files_count', 'total_rows_merged'], ascending=[False, False])

    global_df.to_csv(output_csv, index=False, encoding='utf-8')

    print(f"  [DONE] {len(global_df):,} AI-extracted identities (of {initial_count:,} total) -> {output_csv}")