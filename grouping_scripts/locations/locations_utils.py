import re
import sqlite3
import pandas as pd
import splink.comparison_library as cl
import splink.comparison_level_library as cll

from utils.clean_utils import standardize_nulls

# --- HISTORICAL ABBREVIATION MAP ---
HISTORICAL_ABBREVS = {
    'va': 'virginia', 'ky': 'kentucky', 'kenty': 'kentucky', 'mo': 'missouri', 'md': 'maryland',
    'pa': 'pennsylvania', 'penn': 'pennsylvania', 'penna': 'pennsylvania',
    'tenn': 'tennessee', 'miss': 'mississippi', 'geo': 'georgia', 'ga': 'georgia',
    'mass': 'massachusetts', 'conn': 'connecticut', 'fla': 'florida',
    'ark': 'arkansas', 'lou': 'louisiana', 'la': 'louisiana', 'mich': 'michigan',
    'tex': 'texas', 'dc': 'district of columbia',
    'sc': 'south carolina', 'nc': 'north carolina', 'ny': 'new york', 'nj': 'new jersey',
    'wv': 'west virginia', 'wva': 'west virginia',
    'ca': 'california', 'ala': 'alabama', 'ind': 'indiana', 'ill': 'illinois',
    'co': 'county', 'pty': 'county', 'dist': 'district', 'st': 'saint',
    'mt': 'mount', 'ft': 'fort', 'cmp': 'camp', 'twp': 'township',
    'isld': 'island', 'car': 'carolina', 'so': 'south', 'no': 'north'
}
abbrev_pattern = re.compile(r'\b(' + '|'.join(sorted(HISTORICAL_ABBREVS.keys(), key=len, reverse=True)) + r')\b')

# --- COMPOUND ABBREVIATION PATTERNS ---
# Multi-word abbreviations that can't be safely handled by single-word expansion
COMPOUND_ABBREVS = {
    r'\bs\s*carolina\b': 'south carolina', r'\bn\s*carolina\b': 'north carolina',
    r'\bs\s*car\b': 'south carolina', r'\bn\s*car\b': 'north carolina',
    r'\bw\s*virginia\b': 'west virginia', r'\bw\s*va\b': 'west virginia',
}
compound_pattern = re.compile('|'.join(COMPOUND_ABBREVS.keys()))

# --- GEO SUFFIX STRIPPING ---
# These words are metadata, not part of the core place name (already captured in 'type' column)
GEO_SUFFIXES = re.compile(r'\b(town|city|county|state|country|region|district|township|parish|territory|plantation|camp|fort|island)$')


def clean_location_text(text):
    """Normalize a place name: lowercase, expand abbreviations, strip geo suffixes."""
    if pd.isna(text): return ""
    text = str(text).lower()

    # Step 1: Convert periods, commas, and hyphens to spaces
    text = re.sub(r'[-\.,]', ' ', text)

    # Step 2: Strip any remaining non-alphanumeric characters
    text = re.sub(r'[^\w\s]', '', text)

    # Step 3: Collapse single-letter sequences ("S C" -> "sc", "D C" -> "dc")
    # This fixes "S. C." -> "s c" -> "sc" so abbreviation expansion catches it
    text = re.sub(r'(?<=\b\w)\s+(?=\w\b)', '', text)

    # Step 4: Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()

    # Step 5: Expand historical abbreviations (sc -> south carolina)
    text = abbrev_pattern.sub(lambda m: HISTORICAL_ABBREVS[m.group(0)], text)

    # Step 6: Strip trailing geo suffixes ("beaufort town" -> "beaufort")
    text = GEO_SUFFIXES.sub('', text).strip()

    return text


def clean_geo_field(text):
    """Normalize a structured geo field (state, city, county) for comparison."""
    if pd.isna(text) or str(text).strip() in ('', '--', '---'):
        return None
    text = str(text).lower()
    text = re.sub(r'[-\.,]', ' ', text)
    text = re.sub(r'[^\w\s]', '', text)
    text = re.sub(r'\b(\w)\s+(?=\w\b)', r'\1', text)
    text = re.sub(r'\s+', ' ', text).strip()
    text = abbrev_pattern.sub(lambda m: HISTORICAL_ABBREVS[m.group(0)], text)
    # Strip trailing "county"/"state" etc. so "Coahoma County" == "Coahoma"
    text = GEO_SUFFIXES.sub('', text).strip()
    return text if text else None


def clean_and_merge_context(context_series):
    """Merge contexts while removing exact duplicates and overlapping substrings."""
    valid_strings = [str(i).strip() for i in context_series if pd.notna(i) and str(i).strip() != '']
    unique_strings = list(dict.fromkeys(valid_strings))

    final_strings = []
    for s in unique_strings:
        is_fragment = any(s in other and s != other for other in unique_strings)
        if not is_fragment:
            final_strings.append(s)

    return ' ... '.join(final_strings)

def load_locations_from_db(db_path, custom_where=""):
    """Load and normalize raw location records from the database."""
    print("  [LOAD] Loading raw locations from database...")
    conn = sqlite3.connect(db_path)

    query = f"""
        SELECT 
            id, pdf_file, page, context,
            place_name, type, city, county, state, country 
        FROM locations
        {custom_where}
    """
    df = pd.read_sql_query(query, conn)
    conn.close()

    if df.empty:
        return df

    geo_cols = ['type', 'city', 'county', 'state', 'country']
    df = standardize_nulls(df, geo_cols)

    df['place_name'] = df['place_name'].astype(str).str.strip()

    return df
