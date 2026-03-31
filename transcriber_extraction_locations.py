import asyncio
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from openai import AsyncOpenAI
from openai import LengthFinishReasonError
from pydantic import BaseModel

load_dotenv()

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

DB_FILE = "transcriber_db.db"
BATCH_SIZE = 10

# OpenAI model pricing (USD per 1M tokens)
PRICING = {
    "gpt-4o":       {"input": 2.50,  "output": 10.00},
    "gpt-4o-mini":  {"input": 0.15,  "output": 0.60},
    "gpt-5-mini":   {"input": 0.25,  "output": 2.00},
}

DEFAULT_MODEL = "gpt-4o-mini"

SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "location-extraction.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class Location(BaseModel):
    place_name: str
    type:       str
    city:       str
    county:     str
    state:      str
    country:    str
    context:    str
    reference:  str


class LocationList(BaseModel):
    locations: list[Location]


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def init_db():
    con = sqlite3.connect(DB_FILE)
    con.execute("""
        CREATE TABLE IF NOT EXISTS location_extraction_runs (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at       TEXT NOT NULL,
            transcription_id INTEGER,
            pdf_file         TEXT NOT NULL,
            page             INTEGER NOT NULL,
            model            TEXT NOT NULL,
            input_tokens     INTEGER,
            output_tokens    INTEGER,
            cost_usd         REAL,
            locations_found  INTEGER
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS locations (
            id                         INTEGER PRIMARY KEY AUTOINCREMENT,
            location_extraction_run_id INTEGER NOT NULL,
            transcription_id           INTEGER,
            pdf_file                   TEXT NOT NULL,
            page                       INTEGER NOT NULL,
            place_name                 TEXT,
            type                       TEXT,
            city                       TEXT,
            county                     TEXT,
            state                      TEXT,
            country                    TEXT,
            context                    TEXT,
            reference                  TEXT
        )
    """)
    con.commit()
    return con


def already_extracted(con, pdf_file: str, page: int) -> bool:
    row = con.execute(
        "SELECT id FROM location_extraction_runs WHERE pdf_file = ? AND page = ?",
        (pdf_file, page)
    ).fetchone()
    return row is not None


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

async def extract_locations_from_page(sem, lock, transcription_id: int, pdf_file: str,
                                       page: int, text: str, model: str,
                                       con: sqlite3.Connection) -> tuple[int, list[Location], float]:
    async with sem:
        print(f"  Extracting locations: {Path(pdf_file).name} page {page}...", flush=True)

        locations = []
        in_tok = out_tok = 0
        for attempt in range(3):
            try:
                completion = await client.beta.chat.completions.parse(
                    model=model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user",   "content": text},
                    ],
                    response_format=LocationList,
                )
                in_tok    = completion.usage.prompt_tokens
                out_tok   = completion.usage.completion_tokens
                locations = completion.choices[0].message.parsed.locations
                break
            except LengthFinishReasonError as e:
                print(f"    {Path(pdf_file).name} page {page} — output too long, skipping.", flush=True)
                in_tok  = e.completion.usage.prompt_tokens if e.completion else 0
                out_tok = e.completion.usage.completion_tokens if e.completion else 0
                break
            except Exception as e:
                if attempt == 2:
                    print(f"    {Path(pdf_file).name} page {page} — failed after 3 attempts: {e}", flush=True)
                    break
                wait = 10 * (attempt + 1)
                print(f"    {Path(pdf_file).name} page {page} — error (attempt {attempt+1}/3), retrying in {wait}s: {e}", flush=True)
                await asyncio.sleep(wait)

        cost = calc_cost(model, in_tok, out_tok)

        async with lock:
            run_cur = con.execute("""
                INSERT INTO location_extraction_runs
                    (created_at, transcription_id, pdf_file, page, model,
                     input_tokens, output_tokens, cost_usd, locations_found)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.utcnow().isoformat(),
                transcription_id, pdf_file, page, model,
                in_tok, out_tok, cost, len(locations),
            ))
            run_id = run_cur.lastrowid

            for loc in locations:
                con.execute("""
                    INSERT INTO locations
                        (location_extraction_run_id, transcription_id, pdf_file, page,
                         place_name, type, city, county, state, country, context, reference)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    run_id, transcription_id, pdf_file, page,
                    loc.place_name, loc.type, loc.city, loc.county,
                    loc.state, loc.country, loc.context, loc.reference,
                ))
            con.commit()

        print(f"    {Path(pdf_file).name} page {page} — {len(locations)} location(s) | {in_tok:,} in / {out_tok:,} out | ${cost:.6f}", flush=True)
        return page, locations, cost


async def run_extraction_async(pdf_file: str | None = None, pages: list[int] | None = None,
                                model: str = DEFAULT_MODEL):
    con = init_db()
    rows = get_transcriptions(con, pdf_file=pdf_file, pages=pages)

    if not rows:
        print("No transcriptions found.")
        con.close()
        return

    todo = [r for r in rows if not already_extracted(con, r[1], r[2])]
    skipped = len(rows) - len(todo)
    if skipped:
        print(f"Skipping {skipped} already-extracted page(s).")

    if not todo:
        print("All pages already extracted.")
        con.close()
        return

    print(f"Running location extraction on {len(todo)} page(s) with {model} ({BATCH_SIZE} concurrent)...\n")

    sem  = asyncio.Semaphore(BATCH_SIZE)
    lock = asyncio.Lock()

    tasks = [
        extract_locations_from_page(sem, lock, tid, pf, pg, text, model, con)
        for tid, pf, pg, text in todo
    ]
    results = await asyncio.gather(*tasks)

    con.close()

    total_locations = sum(len(locs) for _, locs, _ in results)
    total_cost      = sum(cost for _, _, cost in results)

    print(f"\n{'─'*50}")
    print(f"TOTALS: {total_locations} locations | ${total_cost:.6f}")
    print(f"{'─'*50}")


def run_extraction(pdf_file: str | None = None, pages: list[int] | None = None,
                   model: str = DEFAULT_MODEL):
    asyncio.run(run_extraction_async(pdf_file=pdf_file, pages=pages, model=model))


if __name__ == "__main__":
    run_extraction(model=DEFAULT_MODEL)
