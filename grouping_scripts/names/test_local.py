import os
import pandas as pd
import splink.comparison_library as cl
import splink.comparison_level_library as cll
from splink import DuckDBAPI, Linker

from names.names_utils import load_persons_from_db, determine_role

# Go up one level from the script to get to 'grouping_scripts', then up one more to get to the main repo
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Point directly to where the DB actually lives
DB_PATH = os.path.join(ROOT_DIR, "transcriber_db.db")

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

PREDICT_THRESHOLD = 0.01
TEST_THRESHOLDS = [0.20, 0.50, 0.65, 0.75]

print("\n[TEST] Local Names Threshold Analysis")
print("=" * 50)
test_filter = """
WHERE (
    pdf_file LIKE '%Jones Jacob%'
    OR pdf_file LIKE '%Brown Frederick%'
    OR pdf_file LIKE '%Green Moses%'
    OR pdf_file LIKE '%Abbs Wilkins%'
    OR pdf_file LIKE '%Clark David%'
    OR pdf_file LIKE '%Bickford Nathan%'
)
"""

df = load_persons_from_db(DB_PATH, custom_where_clause=test_filter)

if df.empty:
    print("  [WARN] No records found for test filter.")
    exit()

print(f"  [LOAD] {len(df):,} raw rows extracted.")


agg_df = df.groupby(['file_id', 'entity_value', 'first_name', 'last_name'], as_index=False).agg({
    'unique_id': 'first',
    'title': lambda x: ' '.join(str(i).lower() for i in x if pd.notna(i) and str(i).strip() != '') or None,
    'context': lambda x: ' '.join(str(i).lower() for i in x if pd.notna(i) and str(i).strip() != '') or None
})

combined_text = agg_df['title'].fillna('') + " " + agg_df['context'].fillna('')
agg_df['role_category'] = combined_text.apply(determine_role)
print(f"  [COLLAPSE] {len(agg_df):,} unique entities for comparison.")

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
    "additional_columns_to_retain": ["first_name", "last_name"],
    "retain_intermediate_calculation_columns": True
}

linker = Linker(agg_df, settings, db_api=DuckDBAPI())

NAMES_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_HTML = os.path.join(NAMES_DIR, "test_local_predictions.html")

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
  .prob-65 { color: #64ffda; font-weight: 600; }
  .prob-50 { color: #ffd93d; }
  .prob-20 { color: #fb8500; }
  .prob-none { color: #8892b0; }
</style>
"""

def _prob_class(val):
    try:
        v = float(val)
        if v >= 0.90: return 'prob-90'
        if v >= 0.65: return 'prob-65'
        if v >= 0.50: return 'prob-50'
        if v >= 0.20: return 'prob-20'
    except (ValueError, TypeError):
        pass
    return 'prob-none'

print("\n  [PREDICT] Running at threshold {:.0%}...".format(PREDICT_THRESHOLD))
try:
    results = linker.inference.predict(threshold_match_probability=PREDICT_THRESHOLD)
    predictions_df = results.as_pandas_dataframe()

    if predictions_df.empty:
        print("  [WARN] Zero comparisons generated.")
    else:
        predictions_df['match_probability'] = predictions_df['match_probability'].round(3)
        predictions_df = predictions_df.sort_values(by='match_probability', ascending=False)

        # Split predictions into Short Names vs Full Names
        def is_short(row):
            fn_l, ln_l = str(row.get('first_name_l', '')), str(row.get('last_name_l', ''))
            fn_r, ln_r = str(row.get('first_name_r', '')), str(row.get('last_name_r', ''))
            return len(fn_l) < 3 or len(ln_l) < 3 or len(fn_r) < 3 or len(ln_r) < 3

        predictions_df['is_short'] = predictions_df.apply(is_short, axis=1)
        
        # Build HTML
        html = [f"<html><head><title>Local Names Test</title>{TABLE_STYLE}</head><body>"]
        html.append("<h1>Local Names Threshold Analysis</h1>")
        html.append(f"<div class='meta'>{len(predictions_df):,} total comparisons &middot; Predict threshold: {PREDICT_THRESHOLD}</div>")
        
        # Legend
        html.append("""
        <div style='background: #2d2d44; padding: 12px; border-radius: 6px; margin-bottom: 24px; display: inline-block;'>
            <div style='margin-bottom: 6px; color: #a8b2d1; font-weight: 600;'>Threshold Legend</div>
            <div class='prob-90'>&ge; 90% &mdash; Very High Confidence</div>
            <div class='prob-65'>&ge; 65% &mdash; High Confidence Match</div>
            <div class='prob-50'>&ge; 50% &mdash; Borderline</div>
            <div class='prob-20'>&ge; 20% &mdash; Review</div>
            <div class='prob-none'>&lt; 20% &mdash; Unlikely</div>
        </div>
        """)

        display_cols = ['match_probability', 'entity_value_l', 'entity_value_r',
                        'gamma_first_name', 'gamma_last_name', 'gamma_entity_value', 'gamma_title',
                        'role_category_l', 'role_category_r']
        cols = [c for c in display_cols if c in predictions_df.columns]

        sections = [
            ("Short Names / Initials (Length < 3)", predictions_df[predictions_df['is_short']]),
            ("Full Names (Length >= 3)", predictions_df[~predictions_df['is_short']])
        ]

        for title, df_subset in sections:
            # Only show pairs >= 0.20 to avoid massive tables of 1% matches, 
            # or if it's small, show them. Let's filter to >= 0.20 for readability.
            matches = df_subset[df_subset['match_probability'] >= 0.20]
            count = len(matches)
            
            html.append(f"<h2>{title} &mdash; {count:,} pairs (&ge; 20%)</h2>")
            
            if count == 0:
                html.append("<p style='color:#8892b0'>No matches &ge; 20% found.</p>")
                continue

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

        html.append("</body></html>")
        with open(OUTPUT_HTML, 'w', encoding='utf-8') as f:
            f.write('\n'.join(html))

        print(f"  [DONE] {len(predictions_df):,} predictions -> {OUTPUT_HTML}")

except Exception as e:
    print(f"  [ERROR] {e}")

