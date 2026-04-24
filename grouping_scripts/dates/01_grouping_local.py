import os
import pandas as pd

from dates.dates_utils import load_dates_from_db
from utils.clean_utils import clean_and_merge_context
from utils.db_utils import update_cluster_ids

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(ROOT_DIR, "transcriber_db.db")
OUTPUT_DIR = os.path.join(ROOT_DIR, "grouping_scripts", "output")

def run_local_dates_dedupe(df, output_filename):
    if df is None or df.empty:
        print("No date records found.")
        return None

    # --- 1. SPLIT DATA ---

    # If ANY of the three fields are missing, it's a partial date.
    mask_partial = df['year'].isna() | df['month'].isna() | df['day'].isna()

    complete_df = df[~mask_partial].copy()
    partial_df = df[mask_partial].copy()

    print(f"   -> Total records loaded: {len(df)}")
    print(f"   -> Complete Dates:       {len(complete_df)} (Will be grouped)")
    print(f"   -> Partial Dates:        {len(partial_df)} (Forced as Singletons)")

    # --- 2. EXACT MATCH COLLAPSE ---
    if not complete_df.empty:
        # We group by exact file and exact date. 
        # The 'id' of the first row in the group becomes the cluster_id for the whole group.
        grouped = complete_df.groupby(['pdf_file', 'year', 'month', 'day'], as_index=False)
        
        # Create a mapping dataframe of the exact matches
        cluster_map = grouped['id'].first().rename(columns={'id': 'cluster_id'})
        
        # Merge the cluster_ids back onto the complete records
        complete_results = complete_df.merge(
            cluster_map, 
            on=['pdf_file', 'year', 'month', 'day'], 
            how='left'
        )
        complete_results['cluster_id'] = complete_results['cluster_id'].astype(str)
        print(f"  [COLLAPSE] {len(complete_df)} complete rows -> {complete_results['cluster_id'].nunique()} precise events")
    else:
        complete_results = pd.DataFrame()

    # --- 3. FORCE PARTIAL DATES TO SINGLETONS ---
    if not partial_df.empty:
        partial_df['cluster_id'] = partial_df['id'].astype(str)
        partial_results = partial_df.copy()
    else:
        partial_results = pd.DataFrame()

    # --- 4. RECOMBINE & AGGREGATE ---
    full_results = pd.concat([complete_results, partial_results], ignore_index=True)

    master_csv_df = full_results.groupby(['pdf_file', 'cluster_id'], as_index=False).agg({
        'month': 'first',
        'day': 'first',
        'year': 'first',
        'date_type': lambda x: ' | '.join(pd.Series(x).dropna().unique()),
        'page': lambda x: ', '.join(sorted(set(str(p).strip() for sub in x.dropna() for p in str(sub).split(',')))),
        'context': clean_and_merge_context
    })

    master_csv_df = master_csv_df.sort_values(by=["pdf_file", "cluster_id"])
    master_csv_df.to_csv(output_filename, index=False, encoding='utf-8')

    print(f"  [DONE] {master_csv_df['cluster_id'].nunique():,} entities -> {output_filename}")

    return full_results

if __name__ == "__main__":
    print("\n[STEP 1] Local Dates Strict Deduplication")
    print("=" * 50)
    
    df_dates = load_dates_from_db(DB_PATH)
    output_csv = os.path.join(OUTPUT_DIR, "LOCAL_DATES_CLUSTERS.csv")
    full_clusters_df = run_local_dates_dedupe(df_dates, output_csv)

    if full_clusters_df is not None:
        update_cluster_ids(DB_PATH, "dates", "id", "cluster_id", full_clusters_df)
