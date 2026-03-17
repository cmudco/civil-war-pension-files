import os
import sqlite3
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

DB_FILE = "transcriber_db.db"
LOG_TO_DB = True

# OpenAI model pricing (USD per 1M tokens)
PRICING = {
    "gpt-4o":       {"input": 2.50,  "output": 10.00},
    "gpt-4o-mini":  {"input": 0.15,  "output": 0.60},
    "gpt-5-mini":   {"input": 0.25,  "output": 2.00},
}

DEFAULT_MODEL = "gpt-4o-mini"

SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "person-extraction.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class Person(BaseModel):
    first_name:     str
    last_name:      str
    middle_name:    str
    middle_initial: str
    prefix:         str
    suffix:         str
    title:          str
    context:        str
    reference:      str


class PersonList(BaseModel):
    persons: list[Person]


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def init_db():
    con = sqlite3.connect(DB_FILE)
    con.execute("""
        CREATE TABLE IF NOT EXISTS extraction_runs (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at       TEXT NOT NULL,
            transcription_id INTEGER,
            pdf_file         TEXT NOT NULL,
            page             INTEGER NOT NULL,
            model            TEXT NOT NULL,
            input_tokens     INTEGER,
            output_tokens    INTEGER,
            cost_usd         REAL,
            persons_found    INTEGER
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS persons (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            extraction_run_id INTEGER NOT NULL,
            transcription_id  INTEGER,
            pdf_file          TEXT NOT NULL,
            page              INTEGER NOT NULL,
            first_name        TEXT,
            last_name         TEXT,
            middle_name       TEXT,
            middle_initial    TEXT,
            prefix            TEXT,
            suffix            TEXT,
            title             TEXT,
            context           TEXT,
            reference         TEXT
        )
    """)
    con.commit()
    return con


def get_transcriptions(con, pdf_file: str | None = None, pages: list[int] | None = None):
    query = "SELECT id, pdf_file, page, result FROM transcriptions WHERE result IS NOT NULL"
    params = []
    if pdf_file:
        query += " AND pdf_file = ?"
        params.append(str(Path(pdf_file)))
    if pages:
        placeholders = ",".join("?" * len(pages))
        query += f" AND page IN ({placeholders})"
        params.extend(pages)
    query += " ORDER BY pdf_file, page"
    return con.execute(query, params).fetchall()


def calc_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    p = PRICING.get(model, PRICING[DEFAULT_MODEL])
    return (input_tokens / 1_000_000) * p["input"] + (output_tokens / 1_000_000) * p["output"]


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def extract_persons_from_page(transcription_id: int, pdf_file: str, page: int,
                               text: str, model: str, con: sqlite3.Connection | None) -> tuple[list[Person], float]:
    print(f"  Extracting persons from page {page} ({pdf_file})...")

    completion = client.beta.chat.completions.parse(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": text},
        ],
        response_format=PersonList,
    )

    usage = completion.usage
    in_tok  = usage.prompt_tokens
    out_tok = usage.completion_tokens
    cost    = calc_cost(model, in_tok, out_tok)
    persons = completion.choices[0].message.parsed.persons

    if con is not None:
        run_cur = con.execute("""
            INSERT INTO extraction_runs
                (created_at, transcription_id, pdf_file, page, model,
                 input_tokens, output_tokens, cost_usd, persons_found)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.utcnow().isoformat(),
            transcription_id, pdf_file, page, model,
            in_tok, out_tok, cost, len(persons),
        ))
        run_id = run_cur.lastrowid

        for p in persons:
            con.execute("""
                INSERT INTO persons
                    (extraction_run_id, transcription_id, pdf_file, page,
                     first_name, last_name, middle_name, middle_initial,
                     prefix, suffix, title, context, reference)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                run_id, transcription_id, pdf_file, page,
                p.first_name, p.last_name, p.middle_name, p.middle_initial,
                p.prefix, p.suffix, p.title, p.context, p.reference,
            ))

        con.commit()

    print(f"    {len(persons)} person(s) found | {in_tok:,} in / {out_tok:,} out | ${cost:.6f}")

    return persons, cost


def print_persons(persons: list[Person]):
    for p in persons:
        print(f"    ┌─ first_name:     {p.first_name}")
        print(f"    │  last_name:      {p.last_name}")
        print(f"    │  middle_name:    {p.middle_name}")
        print(f"    │  middle_initial: {p.middle_initial}")
        print(f"    │  prefix:         {p.prefix}")
        print(f"    │  suffix:         {p.suffix}")
        print(f"    │  title:          {p.title}")
        print(f"    │  context:        {p.context}")
        print(f"    └─ reference:      {p.reference}")
        print()


def run_extraction(pdf_file: str | None = None, pages: list[int] | None = None,
                   model: str = DEFAULT_MODEL):
    con = init_db() if LOG_TO_DB else None

    if LOG_TO_DB:
        rows = get_transcriptions(con, pdf_file=pdf_file, pages=pages)
    else:
        rows = get_transcriptions(sqlite3.connect(DB_FILE), pdf_file=pdf_file, pages=pages)

    if not rows:
        print("No transcriptions found matching the given filters.")
        if con:
            con.close()
        return

    db_status = "saving to DB" if LOG_TO_DB else "NOT saving to DB"
    print(f"Running extraction on {len(rows)} page(s) with {model} ({db_status})...\n")

    total_persons = 0
    total_cost = 0.0
    all_persons: list[tuple[int, list[Person]]] = []

    for transcription_id, pdf_file, page, text in rows:
        persons, cost = extract_persons_from_page(
            transcription_id, pdf_file, page, text, model, con
        )
        total_persons += len(persons)
        total_cost    += cost
        all_persons.append((page, persons))

    if con:
        con.close()

    # Full summary at the end
    print(f"\n{'='*50}")
    print(f"RESULTS SUMMARY")
    print(f"{'='*50}")
    for page, persons in all_persons:
        print(f"\nPage {page} — {len(persons)} person(s):")
        print_persons(persons)

    print(f"\n{'─'*50}")
    print(f"TOTALS: {total_persons} persons | ${total_cost:.6f} | DB logging: {LOG_TO_DB}")
    print(f"{'─'*50}")


if __name__ == "__main__":
    pdf_file = "usct_pension_files/G_H/Green Moses Civil War Pension.pdf"
    pages    = None
    model    = DEFAULT_MODEL

    run_extraction(pdf_file=pdf_file, pages=pages, model=model)
