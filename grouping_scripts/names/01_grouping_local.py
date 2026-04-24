import os
import pandas as pd
import splink.comparison_library as cl
import splink.comparison_level_library as cll
from splink import DuckDBAPI, Linker

from names.names_utils import load_persons_from_db, determine_role, update_database_with_clusters, build_master_list

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(ROOT_DIR, "transcriber_db.db")
OUTPUT_DIR = os.path.join(ROOT_DIR, "grouping_scripts", "output")

# --- SPLINK PROBABILITIES & THRESHOLDS ---
PROB_TWO_RANDOM_RECORDS_MATCH = 0.10

ENTITY_VALUE_JW_THRESH_1 = 0.95
ENTITY_VALUE_JW_THRESH_2 = 0.85

TITLE_JW_THRESH_1 = 0.95
TITLE_JW_THRESH_2 = 0.85

LAST_NAME_JW_THRESH_1 = 0.95
LAST_NAME_JW_THRESH_2 = 0.85

FIRST_NAME_JW_THRESH_1 = 0.85
FIRST_NAME_JW_THRESH_2 = 0.75

FIREWALL_FIRST_NAME_JW_THRESH = 0.65

PREDICT_THRESHOLD = 0.65
CLUSTER_THRESHOLD = 0.65

def run_person_dedupe(df, output_filename):
    if df is None or df.empty:
        print("  [WARN] No records found.")
        return None

    # --- 1. COLLAPSE ---
    agg_df = df.groupby(['file_id', 'entity_value', 'first_name', 'last_name'], as_index=False).agg({
        'unique_id': 'first',
        'title': lambda x: ' '.join(str(i).lower() for i in x if pd.notna(i) and str(i).strip() != '') or None,
        'context': lambda x: ' '.join(str(i).lower() for i in x if pd.notna(i) and str(i).strip() != '') or None
    })

    # --- 2. SCORE ROLES ---
    combined_text = agg_df['title'].fillna('') + " " + agg_df['context'].fillna('')
    agg_df['role_category'] = combined_text.apply(determine_role)

    # --- 3. SPLINK CONFIGURATION ---
    entity_value_comparison = cl.CustomComparison(
        output_column_name="entity_value",
        comparison_levels=[
            cll.NullLevel("entity_value"),
            cll.ExactMatchLevel("entity_value"),
            cll.JaroWinklerLevel("entity_value", ENTITY_VALUE_JW_THRESH_1),
            cll.JaroWinklerLevel("entity_value", ENTITY_VALUE_JW_THRESH_2),
            cll.ElseLevel()
        ]
    )

    title_comparison = cl.CustomComparison(
        output_column_name="title",
        comparison_levels=[
            cll.NullLevel("title"),
            cll.ExactMatchLevel("title"),
            cll.JaroWinklerLevel("title", TITLE_JW_THRESH_1),
            cll.JaroWinklerLevel("title", TITLE_JW_THRESH_2),
            cll.ElseLevel()
        ]
    )

    settings = {
        "link_type": "dedupe_only",
        "probability_two_random_records_match": PROB_TWO_RANDOM_RECORDS_MATCH,
        "comparisons": [
            entity_value_comparison,
            cl.JaroWinklerAtThresholds("last_name", [LAST_NAME_JW_THRESH_1, LAST_NAME_JW_THRESH_2]),
            cl.JaroWinklerAtThresholds("first_name", [FIRST_NAME_JW_THRESH_1, FIRST_NAME_JW_THRESH_2]),
            title_comparison
        ],
        "blocking_rules_to_generate_predictions": [
            f"""
            l.file_id = r.file_id 
            AND NOT (l.role_category = 'primary' AND r.role_category = 'dependent') 
            AND NOT (l.role_category = 'dependent' AND r.role_category = 'primary')
            AND NOT (
                l.first_name != '' AND r.first_name != ''
                AND jaro_winkler_similarity(l.first_name, r.first_name) < {FIREWALL_FIRST_NAME_JW_THRESH}
            )
            """
        ],
        "retain_intermediate_calculation_columns": False
    }

    linker = Linker(agg_df, settings, db_api=DuckDBAPI())

    # --- 4. PREDICTION ---
    results = linker.inference.predict(threshold_match_probability=PREDICT_THRESHOLD)
    clusters = linker.clustering.cluster_pairwise_predictions_at_threshold(results, CLUSTER_THRESHOLD)

    # --- 5. EXPLODE & EXPORT ---
    cluster_df = clusters.as_pandas_dataframe()[['file_id', 'entity_value', 'cluster_id']]
    final_df = df.merge(cluster_df, on=['file_id', 'entity_value'], how='left')

    final_df['cluster_id'] = final_df['cluster_id'].fillna(final_df['unique_id'].astype(str))

    final_df = final_df.sort_values(by=["cluster_id", "file_id"])
    final_df.to_csv(output_filename, index=False)

    print(f"  [DONE] {len(final_df):,} records -> {output_filename}")
    return final_df

if __name__ == "__main__":
    print("\n[STEP 1] Local Name Deduplication")
    print("=" * 50)

    df_people = load_persons_from_db(DB_PATH)

    output_csv = os.path.join(OUTPUT_DIR, "LOCAL_FILE_CLUSTERS.csv")
    local_clusters_df = run_person_dedupe(df_people, output_csv)

    if local_clusters_df is not None:
        update_database_with_clusters(local_clusters_df, DB_PATH)

        master_df = build_master_list(DB_PATH)

        if not master_df.empty:
            master_csv = os.path.join(OUTPUT_DIR, "MASTER_LOCAL_NAMES.csv")
            master_df.to_csv(master_csv, index=False)
            print(f"  [DONE] Master profiles -> {master_csv}")
