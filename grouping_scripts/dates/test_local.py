import os
import pandas as pd
from dates.dates_utils import load_dates_from_db

# Go up one level from the script to get to 'grouping_scripts', then up one more to get to the main repo
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Point directly to where the DB actually lives
DB_PATH = os.path.join(ROOT_DIR, "transcriber_db.db")
LOCATIONS_DIR = os.path.dirname(os.path.abspath(__file__))

def test_local_dates(db_path, output_html):
    print("Loading raw dates from database...")
    df = load_dates_from_db(db_path)
    
    if df.empty:
        print("No date records found.")
        return

    # If ANY of the three fields are missing, it's a partial date.
    mask_partial = df['year'].isna() | df['month'].isna() | df['day'].isna()

    complete_df = df[~mask_partial].copy()
    partial_df = df[mask_partial].copy()

    total_records = len(df)
    total_complete = len(complete_df)
    total_partial = len(partial_df)
    
    merged_clusters_count = 0
    top_clusters = pd.DataFrame()
    
    if not complete_df.empty:
        # We group by exact file and exact date. 
        grouped = complete_df.groupby(['pdf_file', 'year', 'month', 'day'], as_index=False)
        
        # Count sizes to show the biggest clusters
        sizes = grouped.size().sort_values(by='size', ascending=False)
        merged_clusters_count = len(sizes)
        
        top_clusters = sizes.head(50)
        
    html = [
        "<html><head><title>Local Dates Audit Report</title>",
        "<style>",
        "body { font-family: 'Segoe UI', system-ui, sans-serif; background: #1a1a2e; color: #e0e0e0; padding: 24px; }",
        "h1 { color: #a8b2d1; font-size: 24px; margin-bottom: 4px; }",
        ".stats-box { background: #2d2d44; padding: 16px; border-radius: 8px; margin-bottom: 24px; display: inline-block; border-left: 4px solid #64ffda; }",
        ".stat-row { margin-bottom: 8px; font-size: 15px; }",
        ".number { color: #64ffda; font-weight: bold; font-size: 16px; }",
        "table { border-collapse: collapse; width: 100%; margin-bottom: 16px; font-size: 13px; }",
        "th { background: #2d2d44; color: #a8b2d1; padding: 8px 12px; text-align: left; font-weight: 600; }",
        "td { padding: 8px 12px; border-bottom: 1px solid #2d2d44; }",
        "tr:hover { background: #2d2d44; }",
        "</style></head><body>"
    ]
    
    html.append("<h1>Local Dates Deduplication Report</h1>")
    html.append("<div class='stats-box'>")
    html.append(f"<div class='stat-row'>Total Raw Dates Loaded: <span class='number'>{total_records:,}</span></div>")
    html.append(f"<div class='stat-row'>Complete Dates (Y/M/D present): <span class='number'>{total_complete:,}</span></div>")
    html.append(f"<div class='stat-row'>Partial Dates (Forced Singletons): <span class='number'>{total_partial:,}</span></div>")
    html.append(f"<div class='stat-row' style='margin-top: 12px; padding-top: 12px; border-top: 1px solid #4a4a6a;'>Complete Dates merged down to: <span class='number'>{merged_clusters_count:,} clusters</span></div>")
    html.append("</div>")

    if not top_clusters.empty:
        html.append("<h2>Top 50 Largest Exact Date Clusters (Per-File)</h2>")
        html.append("<table><tr><th>Count</th><th>PDF File</th><th>Year</th><th>Month</th><th>Day</th></tr>")
        
        for _, row in top_clusters.iterrows():
            html.append(f"<tr><td>{row['size']}</td><td>{row['pdf_file']}</td><td>{row['year']}</td><td>{row['month']}</td><td>{row['day']}</td></tr>")
        html.append("</table>")
    
    html.append("</body></html>")
    
    with open(output_html, 'w', encoding='utf-8') as f:
        f.write('\n'.join(html))
        
    print(f"Report generated: {output_html}")


if __name__ == "__main__":
    print("\n[TEST] Local Dates Audit Report")
    print("=" * 50)
    audit_html = os.path.join(LOCATIONS_DIR, "test_local_predictions.html")
    test_local_dates(DB_PATH, audit_html)
