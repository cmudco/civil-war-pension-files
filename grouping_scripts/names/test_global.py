import os
import sqlite3
import pandas as pd

# Go up one level from the script to get to 'grouping_scripts', then up one more to get to the main repo
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Point directly to where the DB actually lives
DB_PATH = os.path.join(ROOT_DIR, "transcriber_db.db")
NAMES_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_HTML = os.path.join(NAMES_DIR, "test_global_audit.html")
AUDIT_CSV = os.path.join(ROOT_DIR, "grouping_scripts", "output", "linkage_scores_audit.csv")


def _short_file(path):
    """Extract just the person name from a pdf_file path."""
    if not path or str(path).strip() == '':
        return ''
    return os.path.splitext(os.path.basename(str(path).replace('\\', '/')))[0]


TABLE_STYLE = """
<style>
  body { font-family: 'Segoe UI', system-ui, sans-serif; background: #1a1a2e; color: #e0e0e0; padding: 24px; }
  h1 { color: #a8b2d1; font-size: 20px; margin-bottom: 4px; }
  h2 { color: #64ffda; font-size: 16px; margin: 28px 0 6px; border-bottom: 1px solid #2d2d44; padding-bottom: 4px; }
  h3 { color: #ccd6f6; font-size: 14px; margin: 16px 0 4px; }
  .meta { color: #8892b0; font-size: 13px; margin-bottom: 20px; }
  .stats { color: #64ffda; font-size: 13px; margin: 4px 0 12px; }
  table { border-collapse: collapse; width: 100%; margin-bottom: 8px; font-size: 13px; }
  th { background: #2d2d44; color: #a8b2d1; padding: 6px 10px; text-align: left; font-weight: 600; position: sticky; top: 0; }
  td { padding: 5px 10px; border-bottom: 1px solid #2d2d44; white-space: nowrap; }
  tr:hover { background: #2d2d44; }
  .singleton { color: #8892b0; font-style: italic; font-size: 12px; }
  .merged { color: #64ffda; font-size: 12px; }
</style>
"""


def run_global_audit(db_path, audit_csv_path, patterns):
    """Audit global linkage results and export as a styled HTML report."""
    html = [f"<html><head><title>Global Linkage Audit</title>{TABLE_STYLE}</head><body>"]
    html.append("<h1>Global Names Linkage Audit</h1>")

    for first_pattern, last_pattern in patterns:
        conn = sqlite3.connect(db_path)
        query = f"""
        SELECT 
            cluster_id as local_id, first_name, last_name, pdf_file,
            global_cluster_id as global_id, birth_age, slaveholder_info
        FROM persons
        WHERE first_name LIKE '{first_pattern}%'
          AND last_name LIKE '%{last_pattern}%'
          AND global_cluster_id IS NOT NULL
        """
        db_df = pd.read_sql_query(query, conn)
        conn.close()

        if db_df.empty:
            html.append(f"<h2>{first_pattern}* {last_pattern}*</h2><p class='singleton'>No records found.</p>")
            print(f"  [SKIP] {first_pattern}* {last_pattern}* — no records")
            continue

        # Merge scores
        if os.path.exists(audit_csv_path):
            scores_df = pd.read_csv(audit_csv_path)
            db_df['local_id'] = db_df['local_id'].astype(str)
            scores_df['local_cluster_id_l'] = scores_df['local_cluster_id_l'].astype(str)
            scores_df['local_cluster_id_r'] = scores_df['local_cluster_id_r'].astype(str)

            left = scores_df[['local_cluster_id_l', 'match_probability', 'match_weight']].rename(columns={'local_cluster_id_l': 'id'})
            right = scores_df[['local_cluster_id_r', 'match_probability', 'match_weight']].rename(columns={'local_cluster_id_r': 'id'})
            max_scores = pd.concat([left, right]).groupby('id')[['match_probability', 'match_weight']].max().reset_index()
            df = db_df.merge(max_scores, left_on='local_id', right_on='id', how='left')
        else:
            df = db_df
            df['match_probability'] = None
            df['match_weight'] = None

        df['pdf_short'] = df['pdf_file'].apply(_short_file)
        for col in ['match_probability', 'match_weight']:
            df[col] = pd.to_numeric(df[col], errors='coerce').round(3)

        n_globals = df['global_id'].nunique()
        n_merged = df.groupby('global_id')['local_id'].nunique().gt(1).sum()
        html.append(f"<h2>{first_pattern}* {last_pattern}*</h2>")
        html.append(f"<div class='meta'>{n_globals} global IDs &middot; {n_merged} merged</div>")
        print(f"  [{first_pattern}* {last_pattern}*] {n_globals} global IDs | {n_merged} merged")

        for g_id, group in df.groupby('global_id'):
            n_locals = group['local_id'].nunique()
            display = group.drop_duplicates(subset=['local_id', 'first_name', 'last_name'])

            if n_locals > 1:
                hw = group['match_weight'].max()
                ap = group['match_probability'].mean()
                label = f"Global {g_id} <span class='merged'>— merged {n_locals} clusters (wt: {hw:.3f}, prob: {ap:.3f})</span>"
            else:
                label = f"Global {g_id} <span class='singleton'>— singleton</span>"

            html.append(f"<h3>{label}</h3>")
            html.append("<table><tr><th>Name</th><th>Local ID</th><th>File</th><th>Prob</th><th>Weight</th></tr>")
            for _, row in display.iterrows():
                name = f"{row['first_name']} {row['last_name']}"
                prob_val = row['match_probability']
                prob_str = f"{prob_val:.3f}" if pd.notna(prob_val) else "—"
                wt_val = row['match_weight']
                wt_str = f"{wt_val:.3f}" if pd.notna(wt_val) else "—"
                html.append(f"<tr><td>{name}</td><td>{row['local_id']}</td><td>{row['pdf_short']}</td><td>{prob_str}</td><td>{wt_str}</td></tr>")
            html.append("</table>")

    html.append("</body></html>")

    with open(OUTPUT_HTML, 'w', encoding='utf-8') as f:
        f.write('\n'.join(html))

    print(f"  [DONE] -> {OUTPUT_HTML}")


if __name__ == "__main__":
    print("\n[TEST] Global Names Linkage Audit")
    print("=" * 50)

    # Patterns covering cross-file merges, extracted bios, and singletons
    PATTERNS = [
        # Cross-file merges (high file count)
        ("Ja", "Crof"),       # Jas Crofut — 16 files
        ("E", "Crof"),        # E. A. Crofut — 13 files
        ("Ca", "Brow"),       # Cain Brown — cross-file
        ("Mo", "Gree"),       # Moses Green — 3 global IDs
        # Extracted with bio data
        ("Wilk", "Abb"),      # Wilkins Abbs — has bio
        ("David", "Clark"),   # David Clark — has marriage/family
        ("Fred", "Brow"),     # Frederick Brown — 6 files
        # High-frequency names
        ("W", "Wash"),        # W H Washington — 15 files
        ("Nath", "Bick"),     # Nathan Bickford — 10 files
        ("W", "Sch"),         # W Schuckers etc — singleton test
        # Additional variety
        ("Jo", "Barrett"),    # Joseph Barrett — 11 files
        ("Joh", "Blac"),      # John Black — 9 files
    ]

    run_global_audit(DB_PATH, AUDIT_CSV, PATTERNS)
