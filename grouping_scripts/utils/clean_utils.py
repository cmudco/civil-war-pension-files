import pandas as pd
import splink.comparison_library as cl
import splink.comparison_level_library as cll


def standardize_nulls(df, columns):
    """Standardize empty fields to real Pandas NAs so Splink's NullLevel catches them."""
    for col in columns:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()
            df[col] = df[col].replace({'': pd.NA, 'nan': pd.NA, 'null': pd.NA, 'None': pd.NA, '--': pd.NA})
    return df


def long_text_comparison(col_name, label="Biographical Overlap", m_prob=None, u_prob=None):
    """Bulletproof Jaccard with DuckDB short-string fix."""
    level = {
        "sql_condition": f"""
            CASE 
                WHEN length({col_name}_l) > 2 AND length({col_name}_r) > 2 
                THEN jaccard({col_name}_l, {col_name}_r) >= 0.3
                ELSE 0 
            END
        """,
        "label_for_charts": label
    }
    if m_prob is not None:
        level["m_probability"] = m_prob
    if u_prob is not None:
        level["u_probability"] = u_prob

    return cl.CustomComparison(
        output_column_name=col_name,
        comparison_levels=[
            cll.NullLevel(col_name),
            cll.ExactMatchLevel(col_name),
            level,
            cll.ElseLevel()
        ]
    )

def clean_and_merge_context(x):
    """Merge context strings, splitting by existing separators and removing duplicates to prevent text bloat."""
    seen = set()
    parts = []
    for item in x:
        if pd.notna(item):
            # Split by existing '...' or similar separators if they exist
            for part in str(item).split('...'):
                p = part.strip()
                if p and p not in seen:
                    seen.add(p)
                    parts.append(p)
    return ' ... '.join(parts)
