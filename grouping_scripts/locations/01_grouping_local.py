import os
import pandas as pd
import splink.comparison_library as cl
import splink.comparison_level_library as cll
from splink import DuckDBAPI, Linker

from locations.locations_utils import (
    clean_location_text, clean_and_merge_context, load_locations_from_db,
    clean_geo_field
)
from utils.db_utils import update_cluster_ids

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(ROOT_DIR, "transcriber_db.db")
OUTPUT_DIR = os.path.join(ROOT_DIR, "grouping_scripts", "output")

# --- SPLINK PROBABILITIES & THRESHOLDS ---
PROB_TWO_RANDOM_RECORDS_MATCH = 0.01

PLACE_KEY_JW_THRESH_1 = 0.90 
PLACE_KEY_JW_THRESH_2 = 0.85 

BLOCKING_JW_THRESH = 0.80
PREDICT_THRESHOLD = 0.70
CLUSTER_THRESHOLD = 0.70

def run_local_locations_dedupe(df, output_filename):
    if df is None or df.empty:
        print("  [WARN] No location records found.")
        return None

    # --- 1. SPLIT DATA (VALID VS AUTO-SINGLETONS) ---
    print("\n  [SPLIT] Separating valid records from auto-singletons...")
    df['place_key'] = df['place_name'].apply(clean_location_text)

    # Identify explicit blanks or "--"
    mask_invalid = (df['place_name'] == '--') | (df['place_key'] == '')

    valid_df = df[~mask_invalid].copy()
    invalid_df = df[mask_invalid].copy()

    print(f"    Total records loaded: {len(df)}")
    print(f"    Valid for Splink:     {len(valid_df)}")
    print(f"    Auto-Singletons:      {len(invalid_df)} (Bypassing engine)")

    if not valid_df.empty:
        # Clean structured geo fields for better matching
        for col in ['city', 'county', 'state', 'country']:
            valid_df[col] = valid_df[col].apply(clean_geo_field)

        # --- 2. COLLAPSE ---
        agg_df = valid_df.groupby(['pdf_file', 'place_key'], as_index=False).agg({
            'id': 'first',
            'place_name': lambda x: ' | '.join(pd.Series(x).unique()),
            'type': 'first', 'city': 'first', 'county': 'first', 'state': 'first', 'country': 'first',
            'page': lambda x: ', '.join(sorted(set(str(i) for i in x if pd.notna(i)))),
            'context': clean_and_merge_context
        })

        # --- 3. SPLINK CONFIGURATION ---
        settings = {
            "link_type": "dedupe_only",
            "unique_id_column_name": "id",
            "probability_two_random_records_match": PROB_TWO_RANDOM_RECORDS_MATCH,
            "comparisons": [
                
                # THE HOLISTIC NAME MATCHER
                cl.CustomComparison(
                    output_column_name="place_match",
                    comparison_levels=[
                        cll.NullLevel("place_key"),
                        
                        # Tier 1: Exact, Substring, or Token Overlap AND they are in the exact same State
                        {
                            "sql_condition": """
                                (place_key_l = place_key_r 
                                OR (contains(place_key_l, place_key_r) AND length(place_key_r) >= 4)
                                OR (contains(place_key_r, place_key_l) AND length(place_key_l) >= 4)
                                OR (
                                    length(list_intersect(string_split(place_key_l, ' '), string_split(place_key_r, ' '))) * 1.0 /
                                    NULLIF(least(length(string_split(place_key_l, ' ')), length(string_split(place_key_r, ' '))), 0) >= 0.66
                                    AND length(place_key_l) >= 4 AND length(place_key_r) >= 4
                                ))
                                AND state_l = state_r AND state_l IS NOT NULL
                            """, 
                            "label_for_charts": "Exact/Sub/Overlap + Same State", 
                            "m_probability": 0.95, "u_probability": 0.01
                        },
                        
                        # Tier 2: Exact, Substring, or Token Overlap (But missing/clashing State)
                        {
                            "sql_condition": """
                                place_key_l = place_key_r 
                                OR (contains(place_key_l, place_key_r) AND length(place_key_r) >= 4)
                                OR (contains(place_key_r, place_key_l) AND length(place_key_l) >= 4)
                                OR (
                                    length(list_intersect(string_split(place_key_l, ' '), string_split(place_key_r, ' '))) * 1.0 /
                                    NULLIF(least(length(string_split(place_key_l, ' ')), length(string_split(place_key_r, ' '))), 0) >= 0.66
                                    AND length(place_key_l) >= 4 AND length(place_key_r) >= 4
                                )
                            """, 
                            "label_for_charts": "Exact/Sub/Overlap (No State)", 
                            "m_probability": 0.60, "u_probability": 0.05
                        },
                        
                        # Tier 3 & 4: The Jaro-Winkler Typo Catchers
                        {"sql_condition": f"jaro_winkler_similarity(place_key_l, place_key_r) >= {PLACE_KEY_JW_THRESH_1}", "label_for_charts": "Super High Match", "m_probability": 0.30, "u_probability": 0.10},
                        {"sql_condition": f"jaro_winkler_similarity(place_key_l, place_key_r) >= {PLACE_KEY_JW_THRESH_2}", "label_for_charts": "High Match", "m_probability": 0.10, "u_probability": 0.20},
                        
                        # Tier 5: Massive VETO if JW is less than 50%
                        {"sql_condition": "jaro_winkler_similarity(place_key_l, place_key_r) < 0.50", "label_for_charts": "Terrible Match VETO", "m_probability": 0.0001, "u_probability": 0.99},

                        # Tier 6: Default Mismatch VETO (50% <= JW < 85%)
                        {"sql_condition": "ELSE", "label_for_charts": "Mismatch VETO", "m_probability": 0.001, "u_probability": 0.90}
                    ]
                ),
                
                # THE METADATA BOOSTERS (Strictly Additive / Mathematically Neutral on Mismatch)
                cl.CustomComparison(
                    output_column_name="city_match",
                    comparison_levels=[
                        cll.NullLevel("city"),
                        {"sql_condition": "city_l = city_r", "label_for_charts": "City Match", "m_probability": 0.80, "u_probability": 0.10},
                        {"sql_condition": "ELSE", "label_for_charts": "Neutral Clash", "m_probability": 0.50, "u_probability": 0.50} 
                    ]
                ),
                cl.CustomComparison(
                    output_column_name="county_match",
                    comparison_levels=[
                        cll.NullLevel("county"),
                        {"sql_condition": "county_l = county_r", "label_for_charts": "County Match", "m_probability": 0.80, "u_probability": 0.10},
                        {"sql_condition": "ELSE", "label_for_charts": "Neutral Clash", "m_probability": 0.50, "u_probability": 0.50}
                    ]
                ),
                cl.CustomComparison(
                    output_column_name="state_match",
                    comparison_levels=[
                        cll.NullLevel("state"),
                        {"sql_condition": "state_l = state_r", "label_for_charts": "State Match", "m_probability": 0.80, "u_probability": 0.10},
                        {"sql_condition": "ELSE", "label_for_charts": "Neutral Clash", "m_probability": 0.50, "u_probability": 0.50}
                    ]
                ),
                cl.CustomComparison(
                    output_column_name="country_match",
                    comparison_levels=[
                        cll.NullLevel("country"),
                        {"sql_condition": "country_l = country_r", "label_for_charts": "Country Match", "m_probability": 0.80, "u_probability": 0.10},
                        {"sql_condition": "ELSE", "label_for_charts": "Neutral Clash", "m_probability": 0.50, "u_probability": 0.50}
                    ]
                ),
                cl.CustomComparison(
                    output_column_name="type_match",
                    comparison_levels=[
                        cll.NullLevel("type"),
                        {"sql_condition": "type_l = type_r", "label_for_charts": "Type Match", "m_probability": 0.60, "u_probability": 0.20},
                        {"sql_condition": "ELSE", "label_for_charts": "Neutral Clash", "m_probability": 0.50, "u_probability": 0.50}
                    ]
                )
            ],
            "blocking_rules_to_generate_predictions": [
                f"""
                l.pdf_file = r.pdf_file 
                AND (
                    l.place_key = r.place_key 
                    OR jaro_winkler_similarity(l.place_key, r.place_key) >= {BLOCKING_JW_THRESH}
                )
                """
            ]
        }

        linker = Linker(agg_df, settings, db_api=DuckDBAPI())
        linker.training.estimate_probability_two_random_records_match(["l.pdf_file = r.pdf_file"], recall=0.9)

        # --- 4. PREDICTION ---
        predictions = linker.inference.predict(threshold_match_probability=PREDICT_THRESHOLD)
        clusters = linker.clustering.cluster_pairwise_predictions_at_threshold(predictions, CLUSTER_THRESHOLD)

        # --- 5. EXPLODE & EXPORT ---
        cluster_df = clusters.as_pandas_dataframe()[['id', 'cluster_id']]
        final_agg = agg_df.merge(cluster_df, on='id', how='left')
        final_agg['cluster_id'] = final_agg['cluster_id'].fillna(final_agg['id'].astype(str))

        valid_results = valid_df[['id', 'pdf_file', 'place_key']].merge(
            final_agg[['pdf_file', 'place_key', 'cluster_id']],
            on=['pdf_file', 'place_key'],
            how='left'
        )
    else:
        final_agg = pd.DataFrame()
        valid_results = pd.DataFrame()

    if not invalid_df.empty:
        invalid_df['cluster_id'] = invalid_df['id'].astype(str)
        invalid_results = invalid_df[['id', 'pdf_file', 'place_key', 'cluster_id']]
        invalid_agg = invalid_df.copy()
        invalid_agg['page'] = invalid_agg['page'].astype(str)
    else:
        invalid_results = pd.DataFrame()
        invalid_agg = pd.DataFrame()

    full_results = pd.concat([valid_results, invalid_results], ignore_index=True)
    combined_agg = pd.concat([final_agg, invalid_agg], ignore_index=True)

    master_csv_df = combined_agg.groupby(['pdf_file', 'cluster_id'], as_index=False).agg({
        'place_name': lambda x: ' | '.join(pd.Series(x).unique()),
        'type': 'first',
        'city': 'first',
        'county': 'first',
        'state': 'first',
        'country': 'first',
        'page': lambda x: ', '.join(sorted(set(p.strip() for sub in x.dropna() for p in str(sub).split(',')))),
        'context': clean_and_merge_context
    })

    master_csv_df = master_csv_df.sort_values(by=["pdf_file", "cluster_id"])
    master_csv_df.to_csv(output_filename, index=False, encoding='utf-8')

    print(f"  [DONE] {master_csv_df['cluster_id'].nunique():,} entities -> {output_filename}")

    return full_results


if __name__ == "__main__":
    print("\n[STEP 1] Local Location Deduplication")
    print("=" * 50)

    df_locs = load_locations_from_db(DB_PATH)

    output_csv = os.path.join(OUTPUT_DIR, "LOCAL_LOCATIONS_CLUSTERS.csv")
    full_clusters_df = run_local_locations_dedupe(df_locs, output_csv)

    if full_clusters_df is not None:
        update_cluster_ids(DB_PATH, "locations", "id", "cluster_id", full_clusters_df)