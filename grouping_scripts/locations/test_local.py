import os
import pandas as pd
import splink.comparison_library as cl
import splink.comparison_level_library as cll
from splink import DuckDBAPI, Linker

from locations.locations_utils import (
    clean_location_text, load_locations_from_db,
    clean_geo_field
)
from utils.clean_utils import standardize_nulls

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(ROOT_DIR, "transcriber_db.db")
OUTPUT_DIR = os.path.join(ROOT_DIR, "grouping_scripts", "output")

# --- SPLINK PROBABILITIES & THRESHOLDS ---
PROB_TWO_RANDOM_RECORDS_MATCH = 0.01

PLACE_KEY_JW_THRESH_1 = 0.90
PLACE_KEY_JW_THRESH_2 = 0.85

BLOCKING_JW_THRESH = 0.80

PREDICT_THRESHOLD = 0.01
DISPLAY_THRESHOLD = 0.10

def test_location_thresholds(db_path, audit_csv_path):
    """Run Splink on locations at a very low threshold and print a score distribution audit."""
    print("  [LOAD] Loading raw locations from database...")
    import sqlite3
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query("SELECT id, pdf_file, place_name, type, city, county, state, country FROM locations", conn)
    conn.close()

    if df.empty:
        print("  [WARN] No location records found.")
        return

    # --- 1. CLEAN ---
    geo_cols = ['type', 'city', 'county', 'state', 'country']
    df = standardize_nulls(df, geo_cols)

    df['place_key'] = df['place_name'].astype(str).apply(clean_location_text)
    for col in ['city', 'county', 'state', 'country']:
        df[col] = df[col].apply(clean_geo_field)

    # --- 2. SPLIT (MIRROR MAIN PIPELINE) ---
    mask_invalid = (df['place_name'] == '--') | (df['place_key'] == '')
    valid_df = df[~mask_invalid].copy()

    print(f"    Ignoring {mask_invalid.sum()} auto-singletons ('--' or blank).")

    # --- 3. COLLAPSE ---
    agg_df = valid_df.groupby(['pdf_file', 'place_key'], as_index=False).agg({
        'id': 'first',
        'place_name': 'first',
        'type': 'first', 'city': 'first', 'county': 'first', 'state': 'first', 'country': 'first'
    })

    print(f"  [COLLAPSE] {len(agg_df):,} unique local strings for comparison.")

    # --- 4. SPLINK CONFIGURATION ---
    settings = {
        "link_type": "dedupe_only",
        "unique_id_column_name": "id",
        "probability_two_random_records_match": PROB_TWO_RANDOM_RECORDS_MATCH,
        "additional_columns_to_retain": ["place_name"],
        "comparisons": [
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

    # --- 5. PREDICT ---
    print(f"\n  [PREDICT] Running at threshold {PREDICT_THRESHOLD:.0%}...")
    predictions = linker.inference.predict(threshold_match_probability=PREDICT_THRESHOLD)
    scores_df = predictions.as_pandas_dataframe()

    if scores_df.empty:
        print("  [WARN] No pairs generated. Check your blocking rules!")
        return

    scores_df['match_probability'] = scores_df['match_probability'].round(3)
    scores_df = scores_df.sort_values(by='match_probability', ascending=False)

    # --- 6. BUILD HTML REPORT ---
    TABLE_STYLE = """
    <style>
      body { font-family: 'Segoe UI', system-ui, sans-serif; background: #1a1a2e; color: #e0e0e0; padding: 24px; }
      h1 { color: #a8b2d1; font-size: 20px; margin-bottom: 4px; }
      h2 { color: #64ffda; font-size: 15px; margin: 24px 0 6px; border-bottom: 1px solid #2d2d44; padding-bottom: 4px; }
      .meta { color: #8892b0; font-size: 13px; margin-bottom: 16px; }
      table { border-collapse: collapse; width: 100%; margin-bottom: 16px; font-size: 13px; }
      th { background: #2d2d44; color: #a8b2d1; padding: 6px 10px; text-align: left; font-weight: 600; position: sticky; top: 0; }
      td { padding: 5px 10px; border-bottom: 1px solid #2d2d44; }
      tr:hover { background: #2d2d44; }
      .prob-90 { color: #4ade80; font-weight: 700; }
      .prob-80 { color: #2dd4bf; font-weight: 600; }
      .prob-70 { color: #64ffda; font-weight: 600; }
      .prob-50 { color: #ffd93d; }
      .prob-20 { color: #fb8500; }
      .prob-none { color: #8892b0; }
    </style>
    """

    def _prob_class(val):
        try:
            v = float(val)
            if v >= 0.90: return 'prob-90'
            if v >= 0.80: return 'prob-80'
            if v >= 0.70: return 'prob-70'
            if v >= 0.50: return 'prob-50'
            if v >= 0.20: return 'prob-20'
        except (ValueError, TypeError):
            pass
        return 'prob-none'

    html = [f"<html><head><title>Local Locations Test</title>{TABLE_STYLE}</head><body>"]
    html.append("<h1>Local Locations Threshold Analysis</h1>")
    html.append(f"<div class='meta'>{len(scores_df):,} total comparisons &middot; Predict threshold: {PREDICT_THRESHOLD}</div>")
    
    html.append("""
    <div style='background: #2d2d44; padding: 12px; border-radius: 6px; margin-bottom: 24px; display: inline-block;'>
        <div style='margin-bottom: 6px; color: #a8b2d1; font-weight: 600;'>Threshold Legend</div>
        <div class='prob-90'>&ge; 90% &mdash; Very High Confidence</div>
        <div class='prob-80'>&ge; 80% &mdash; High Confidence</div>
        <div class='prob-70'>&ge; 70% &mdash; Accepted Match</div>
        <div class='prob-50'>&ge; 50% &mdash; Borderline (Rejected)</div>
        <div class='prob-20'>&ge; 20% &mdash; Review (Rejected)</div>
        <div class='prob-none'>&lt; 20% &mdash; Unlikely (Rejected)</div>
    </div>
    """)

    display_cols = ['match_probability', 'place_name_l', 'place_name_r',
                    'city_l', 'city_r', 'county_l', 'county_r', 'state_l', 'state_r', 'type_l', 'type_r']
    cols = [c for c in display_cols if c in scores_df.columns]

    matches = scores_df[scores_df['match_probability'] >= DISPLAY_THRESHOLD]
    html.append(f"<h2>All Matches &ge; {DISPLAY_THRESHOLD:.0%} &mdash; {len(matches):,} pairs</h2>")

    if not matches.empty:
        html.append("<table><tr>" + "".join(f"<th>{c}</th>" for c in cols) + "</tr>")
        for _, row in matches[cols].iterrows():
            cells = []
            for c in cols:
                val = row[c]
                if c == 'match_probability':
                    cls = _prob_class(val)
                    cells.append(f"<td class='{cls}'>{val:.3f}</td>")
                else:
                    cells.append(f"<td>{val if pd.notna(val) else ''}</td>")
            html.append("<tr>" + "".join(cells) + "</tr>")
        html.append("</table>")
    else:
        html.append(f"<p style='color:#8892b0'>No matches &ge; {DISPLAY_THRESHOLD:.0%} found.</p>")

    html.append("</body></html>")
    
    with open(audit_csv_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(html))

    print(f"  [DONE] {len(scores_df):,} predictions -> {audit_csv_path}")

if __name__ == "__main__":
    print("\n[TEST] Local Locations Threshold Analysis")
    print("=" * 50)

    LOCATIONS_DIR = os.path.dirname(os.path.abspath(__file__))
    audit_html = os.path.join(LOCATIONS_DIR, "test_local_predictions.html")
    test_location_thresholds(DB_PATH, audit_html)
