"""
04_name_matcher.py

Reads all extracted person names from the database, scans all available
PDF files, and scores each unprocessed file by how many times the
soldier named in that file is mentioned across already-processed files.

Run this after each batch of transcriptions to identify the next targets.
"""

import re
import sqlite3
from pathlib import Path

DB_FILE  = "transcriber_db.db"
PDF_ROOT = Path("usct_pension_files")
TOP_N    = 40  # candidates to display

# Suffixes to strip before parsing the name out of a filename
_STRIP = re.compile(
    r"\s*(civil war navy pension|civil war pension|cw pension|"
    r"pension app(lication)?|d \d+\w* usct|g \d+\w* usc\w*|"
    r"e \d+\w* usc\w*|54th ma infantry|redo \w+ \d+)"
    r".*",
    re.IGNORECASE,
)


def normalize(s: str) -> str:
    return s.strip().lower()


def parse_name_tokens(stem: str) -> list[str]:
    """
    Extract name tokens from a PDF filename stem.
    - Strips 'Civil War Pension' and similar suffixes
    - Removes parenthetical content (aliases)
    - Handles 'LastName, FirstName' commas
    Returns a list of tokens, typically [last, first] or [last, first, middle].
    """
    name = _STRIP.sub("", stem).strip()

    # Handle "aka ..." inside parens before removing parens
    name = re.sub(r"\(aka[^)]*\)", "", name, flags=re.IGNORECASE)

    # Remove remaining parenthetical content (aliases like "(Jones)", "(Bryan)")
    name = re.sub(r"\(.*?\)", "", name).strip()

    # Normalize commas to spaces: "Robinson, Lucius" → "Robinson Lucius"
    name = name.replace(",", " ")

    return [t for t in name.split() if t]


def load_name_index(con: sqlite3.Connection) -> dict[tuple[str, str], dict]:
    """
    Build a lookup: (norm_first, norm_last) → {mentions, file_count, files}.
    Excludes placeholder '--' values.
    """
    rows = con.execute("""
        SELECT first_name, last_name,
               COUNT(*)                 AS mentions,
               COUNT(DISTINCT pdf_file) AS file_count,
               GROUP_CONCAT(pdf_file, '|') AS files
        FROM persons
        WHERE first_name NOT IN ('--', '')
          AND last_name  NOT IN ('--', '')
        GROUP BY LOWER(first_name), LOWER(last_name)
    """).fetchall()

    index = {}
    for first, last, mentions, file_count, files in rows:
        key = (normalize(first), normalize(last))
        index[key] = {
            "first":      first,
            "last":       last,
            "mentions":   mentions,
            "file_count": file_count,
            "files":      set(files.split("|")),
        }
    return index


def load_done_files(con: sqlite3.Connection) -> set[str]:
    rows = con.execute("SELECT DISTINCT pdf_file FROM transcriptions").fetchall()
    return {Path(r[0]).as_posix() for r in rows}


def match_tokens(tokens: list[str], index: dict) -> list[dict]:
    """
    Try to find this PDF's soldier name in the index.

    Strategy:
      - Most filenames are LastName FirstName [Middle?]
      - Try (first=tokens[1], last=tokens[0]) — the common case
      - Try (first=tokens[0], last=tokens[1]) — reversed
      - For 3-token names also try (first=tokens[2], last=tokens[0])
    """
    if len(tokens) < 2:
        return []

    candidates = set()
    # Generate (first_idx, last_idx) pairs to try
    pairs = [(1, 0), (0, 1)]
    if len(tokens) >= 3:
        pairs += [(2, 0), (0, 2)]

    matches = []
    for fi, li in pairs:
        key = (normalize(tokens[fi]), normalize(tokens[li]))
        if key in index and key not in candidates:
            candidates.add(key)
            matches.append(index[key])

    return matches


def format_sources(entry: dict, done_files: set[str]) -> str:
    """Show which already-processed files mention this name."""
    stems = []
    for f in sorted(entry["files"]):
        p = Path(f)
        stems.append(p.stem[:40])
    return " / ".join(stems)


def main():
    con = sqlite3.connect(DB_FILE)

    name_index = load_name_index(con)
    done_files = load_done_files(con)

    print(f"Unique person names in DB : {len(name_index):,}")
    print(f"Already-processed files   : {len(done_files)}")
    print()

    all_pdfs    = sorted(PDF_ROOT.rglob("*.pdf"))
    candidates  = []
    no_match    = 0

    for pdf in all_pdfs:
        if pdf.as_posix() in done_files:
            continue
        tokens  = parse_name_tokens(pdf.stem)
        matches = match_tokens(tokens, name_index)

        if not matches:
            no_match += 1
            continue

        # Aggregate across all matches for this file
        total_mentions   = sum(m["mentions"]   for m in matches)
        total_file_count = sum(m["file_count"] for m in matches)
        match_labels     = [f"{m['first']} {m['last']}" for m in matches]
        source_files     = sorted({f for m in matches for f in m["files"]})

        candidates.append({
            "pdf":          pdf,
            "mentions":     total_mentions,
            "file_count":   total_file_count,
            "match_labels": match_labels,
            "sources":      source_files,
        })

    # Sort: most mentions first, then file_count, then alphabetical
    candidates.sort(key=lambda x: (-x["mentions"], -x["file_count"], str(x["pdf"])))

    total_unprocessed = len(candidates) + no_match
    print(f"Unprocessed PDFs    : {total_unprocessed}")
    print(f"With name matches   : {len(candidates)}")
    print(f"No matches (hidden) : {no_match}")
    print()
    print(f"Top {min(TOP_N, len(candidates))} candidates - sorted by mention count\n")

    col_w = 58
    print(f"{'Mentions':>8}  {'In # files':>10}  {'PDF file':<{col_w}}  Matched as  ->  Mentioned in")
    print("-" * 160)

    for c in candidates[:TOP_N]:
        label    = ", ".join(c["match_labels"])
        sources  = " / ".join(Path(f).stem for f in c["sources"])
        pdf_str  = str(c["pdf"])
        # Trim long path for display
        if len(pdf_str) > col_w:
            pdf_str = "~" + pdf_str[-(col_w - 1):]
        print(f"  {c['mentions']:>6}    {c['file_count']:>8}    {pdf_str:<{col_w}}  {label:<30}  {sources}")

    con.close()


if __name__ == "__main__":
    main()
