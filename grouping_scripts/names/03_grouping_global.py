import os
import sqlite3
import pandas as pd
from dotenv import load_dotenv
import splink.comparison_library as cl
import splink.comparison_level_library as cll
from splink import DuckDBAPI, Linker

from utils.clean_utils import standardize_nulls, long_text_comparison
from names.names_utils import build_master_list, generate_global_master_csv

load_dotenv()
# Go up one level from the script to get to 'grouping_scripts', then up one more to get to the main repo
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Point directly to where the DB actually lives
DB_PATH = os.path.join(ROOT_DIR, "transcriber_db.db")
OUTPUT_DIR = os.path.join(ROOT_DIR, "grouping_scripts", "output")

# --- SPLINK PROBABILITIES & THRESHOLDS ---
PROB_TWO_RANDOM_RECORDS_MATCH = 0.01

NAME_EXACT_MATCH_PROB = 0.85
NAME_ALT_MATCH_PROB = 0.10
FILE_CLASH_PROB = 0.01

PREDICT_THRESHOLD = 0.0
CLUSTER_THRESHOLD = 0.6


def run_splink_linkage():
    print("\n[STEP 3] Global Entity Resolution")
    print("=" * 50)
    master_df = build_master_list(DB_PATH)
    if master_df.empty:
        return

    master_df = master_df.rename(columns={'cluster_id': 'local_cluster_id'})

    text_cols = ['canonical_name', 'alt_name', 'birth_age', 'slaveholder_info', 'marriage_info', 'family_members', 'pdf_file']
    master_df = standardize_nulls(master_df, text_cols)

    settings = {
        "link_type": "dedupe_only",
        "unique_id_column_name": "local_cluster_id",
        "additional_columns_to_retain": ["pdf_file", "alt_name", "gemini_extracted"],
        "probability_two_random_records_match": PROB_TWO_RANDOM_RECORDS_MATCH,
        "comparisons": [
            # --- 1. NAME MATCH ---
            cl.CustomComparison(
                output_column_name="name_match",
                comparison_levels=[
                    cll.NullLevel("canonical_name"),
                    {
                        "sql_condition": "canonical_name_l = canonical_name_r",
                        "label_for_charts": "Exact Match",
                        "m_probability": NAME_EXACT_MATCH_PROB
                    },
                    {
                        "sql_condition": "canonical_name_l = alt_name_r OR alt_name_l = canonical_name_r",
                        "label_for_charts": "Canonical/Alt Match",
                        "m_probability": NAME_ALT_MATCH_PROB
                    },
                    cll.ElseLevel()
                ]
            ),

            # --- 2. THE FIREWALL ---
            cl.CustomComparison(
                output_column_name="file_clash",
                comparison_levels=[
                    cll.NullLevel("pdf_file"),
                    {
                        "sql_condition": "pdf_file_l = pdf_file_r",
                        "label_for_charts": "Within-File Clash",
                        "m_probability": FILE_CLASH_PROB
                    },
                    cll.ElseLevel()
                ]
            ),

            # --- 3. THE 4 CRITERIA (BIO FIELDS) ---
            long_text_comparison("slaveholder_info"),
            long_text_comparison("family_members"),
            long_text_comparison("birth_age"),
            long_text_comparison("marriage_info")
        ],

        "blocking_rules_to_generate_predictions": [
            "l.canonical_name = r.canonical_name AND l.canonical_name IS NOT NULL AND l.canonical_name != ''",
            "l.canonical_name = r.alt_name AND l.canonical_name IS NOT NULL AND l.canonical_name != ''",
            "l.alt_name = r.canonical_name AND l.alt_name IS NOT NULL AND l.alt_name != ''",
            "l.slaveholder_info = r.slaveholder_info AND l.slaveholder_info IS NOT NULL AND l.slaveholder_info != ''"
        ]
    }

    linker = Linker(master_df, settings, db_api=DuckDBAPI())

    linker.training.estimate_u_using_random_sampling(max_pairs=1e6, seed=2026)

    predictions = linker.inference.predict(threshold_match_probability=PREDICT_THRESHOLD)

    predict_df = predictions.as_pandas_dataframe()
    audit_csv = os.path.join(OUTPUT_DIR, "linkage_scores_audit.csv")
    predict_df.to_csv(audit_csv, index=False)
    print(f"  [AUDIT] Scores saved -> {audit_csv}")

    clusters = linker.clustering.cluster_pairwise_predictions_at_threshold(predictions, CLUSTER_THRESHOLD)
    cluster_df = clusters.as_pandas_dataframe()

    if 'cluster_id' in cluster_df.columns:
        cluster_df = cluster_df.rename(columns={'cluster_id': 'global_cluster_id'})

    print(f"  [RESULT] {cluster_df['global_cluster_id'].nunique():,} global entities")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    updates = list(cluster_df[['global_cluster_id', 'local_cluster_id']].itertuples(index=False, name=None))
    cursor.executemany("UPDATE persons SET global_cluster_id = ? WHERE cluster_id = ?", updates)
    conn.commit()
    conn.close()

    # --- COMPRESSION METRICS (EXTRACTIONS ONLY) ---
    flag_map = dict(zip(master_df['local_cluster_id'], master_df['gemini_extracted']))

    eval_df = cluster_df.copy()
    eval_df['gemini_extracted'] = eval_df['local_cluster_id'].map(flag_map)

    eval_df = eval_df[eval_df['gemini_extracted'].astype(str).str.strip().isin(['1', '1.0'])]

    if not eval_df.empty:
        total_local = eval_df['local_cluster_id'].nunique()
        total_global = eval_df['global_cluster_id'].nunique()
        compression_rate = (1 - (total_global / total_local)) * 100 if total_local > 0 else 0
        cluster_sizes = eval_df.groupby('global_cluster_id')['local_cluster_id'].count()
        singletons = (cluster_sizes == 1).sum()
        multi_clusters = (cluster_sizes > 1).sum()

        print(f"\n  [METRICS] AI-Extracted Subset")
        print(f"    Input:  {total_local:,} local profiles")
        print(f"    Output: {total_global:,} global entities ({compression_rate:.1f}% compression)")
        print(f"    Merged: {total_local - singletons:,} profiles into {multi_clusters:,} clusters | {singletons:,} singletons")
    else:
        print("\n  [METRICS] No AI-extracted records yet.")

    # --- FINAL EXPORT ---
    global_master_csv = os.path.join(OUTPUT_DIR, "GLOBAL_MASTER_EXTRACTED.csv")
    generate_global_master_csv(DB_PATH, global_master_csv)
    print("  [DONE] Global resolution complete.\n")


if __name__ == "__main__":
    run_splink_linkage()
