"""
XX_story_teller.py

Generates a narrative story report for every transcribed pension file in
the database, using Gemini, OpenAI, and Anthropic in parallel.

Each file gets its own subfolder under stories/:
    stories/Brown_Adam_Civil_War_Pension/
        gemini.md
        openai.md
        anthropic.md

Usage:
    python XX_story_teller.py                  # process all files not yet done
    python XX_story_teller.py --overwrite      # regenerate all, even existing
    python XX_story_teller.py "usct_pension_files/A_B/Brown Adam Civil War Pension.pdf"
"""

import asyncio
import io
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import anthropic
import boto3
from dotenv import load_dotenv
from google import genai
from google.genai import types
from openai import AsyncOpenAI

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DB_FILE     = "transcriber_db.db"
PROMPT_FILE = Path(__file__).parent / "prompts" / "story-teller.md"

S3_BUCKET = os.getenv("S3_BUCKET_NAME", "")
_CF_BASE  = (os.getenv("CLOUDFRONT_BASE_URL") or "").rstrip("/")
s3_client = boto3.client(
    "s3",
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    region_name=os.getenv("AWS_REGION", "us-east-1"),
)


def cf_url(key: str) -> str:
    return f"{_CF_BASE}/{key}"

GEMINI_MODEL    = "gemini-3.1-pro-preview"
OPENAI_MODEL    = "gpt-5.4"
ANTHROPIC_MODEL = "claude-opus-4-6"

# Gemini max output: 65,536 | OpenAI: 128,000 | Anthropic: 128,000
MAX_OUTPUT_TOKENS = 16_384

# Safety cap — max files to process in a single run (applies to not-yet-done files only).
# Override at runtime with --limit N.
DEFAULT_BATCH_LIMIT = 3

PRICING = {
    "gemini":    {"input": 2.00,  "output": 12.00},  # <= 200k input tier
    "openai":    {"input": 2.50,  "output": 15.00},
    "anthropic": {"input": 5.00,  "output": 25.00},
}

MODELS = [
    ("gemini",    GEMINI_MODEL),
    ("openai",    OPENAI_MODEL),
    ("anthropic", ANTHROPIC_MODEL),
]


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------

def get_all_transcribed_files() -> list[str]:
    con = sqlite3.connect(DB_FILE)
    rows = con.execute(
        "SELECT DISTINCT pdf_file FROM transcriptions "
        "WHERE result IS NOT NULL ORDER BY pdf_file"
    ).fetchall()
    con.close()
    return [r[0] for r in rows]


def load_transcriptions(pdf_file: str) -> list[dict]:
    con = sqlite3.connect(DB_FILE)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT page, result FROM transcriptions "
        "WHERE pdf_file = ? AND result IS NOT NULL ORDER BY page",
        (pdf_file,)
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def build_document(rows: list[dict]) -> str:
    return "\n\n".join(f"=== PAGE {r['page']} ===\n{r['result']}" for r in rows)


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def pdf_stem(pdf_file: str) -> str:
    return Path(pdf_file).stem.replace(" ", "_")


def already_done(pdf_file: str) -> bool:
    """Check if all three model stories are already in the DB/S3."""
    stem = pdf_stem(pdf_file)
    con = sqlite3.connect(DB_FILE)
    count = con.execute(
        "SELECT COUNT(*) FROM stories WHERE pdf_stem = ? AND s3_url IS NOT NULL",
        (stem,)
    ).fetchone()[0]
    con.close()
    return count >= len(MODELS)


# ---------------------------------------------------------------------------
# Cost
# ---------------------------------------------------------------------------

def calc_cost(model_key: str, in_tok: int, out_tok: int) -> float:
    p = PRICING[model_key]
    return (in_tok / 1_000_000) * p["input"] + (out_tok / 1_000_000) * p["output"]


# ---------------------------------------------------------------------------
# Model calls
# ---------------------------------------------------------------------------

async def call_gemini(system_prompt: str, document: str) -> tuple[str, int, int]:
    gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        lambda: gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=f"{system_prompt}\n\n{document}",
            config=types.GenerateContentConfig(max_output_tokens=MAX_OUTPUT_TOKENS),
        )
    )
    usage = response.usage_metadata
    return response.text, usage.prompt_token_count or 0, usage.candidates_token_count or 0


async def call_openai(system_prompt: str, document: str) -> tuple[str, int, int]:
    client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    response = await client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": document},
        ],
        max_completion_tokens=MAX_OUTPUT_TOKENS,
    )
    return (
        response.choices[0].message.content,
        response.usage.prompt_tokens,
        response.usage.completion_tokens,
    )


async def call_anthropic(system_prompt: str, document: str) -> tuple[str, int, int]:
    client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    response = await client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": document}],
    )
    text = "".join(b.text for b in response.content if hasattr(b, "text"))
    return text, response.usage.input_tokens, response.usage.output_tokens


CALLERS = {
    "gemini":    call_gemini,
    "openai":    call_openai,
    "anthropic": call_anthropic,
}


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------

def save_story(pdf_file: str, model_key: str, model_name: str,
               text: str, in_tok: int, out_tok: int, cost: float) -> str:
    """Upload story to S3, log to stories table. Returns CloudFront URL."""
    stem = pdf_stem(pdf_file)
    key  = f"stories/{stem}/{model_key}.md"

    header = (
        f"# {Path(pdf_file).stem}\n\n"
        f"**Model:** `{model_name}`  \n"
        f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}  \n"
        f"**Tokens:** {in_tok:,} in / {out_tok:,} out  \n"
        f"**Cost:** ${cost:.4f}  \n\n"
        f"---\n\n"
    )
    content = header + (text or "")
    data = content.encode("utf-8")
    s3_client.upload_fileobj(
        io.BytesIO(data), S3_BUCKET, key,
        ExtraArgs={"ContentType": "text/markdown; charset=utf-8"},
    )
    url = cf_url(key)

    con = sqlite3.connect(DB_FILE)
    con.execute("""
        INSERT INTO stories (created_at, pdf_stem, model, s3_key, s3_url, content)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (datetime.now(timezone.utc).isoformat(), stem, model_key, key, url, content))
    con.commit()
    con.close()

    return url


# ---------------------------------------------------------------------------
# Per-file processing
# ---------------------------------------------------------------------------

async def generate_stories_for_file(pdf_file: str, system_prompt: str,
                                    file_idx: int, total: int):
    label = Path(pdf_file).stem
    print(f"\n[{file_idx}/{total}] {label}")

    rows = load_transcriptions(pdf_file)
    if not rows:
        print(f"  No transcriptions found, skipping.")
        return 0.0

    document = build_document(rows)
    print(f"  {len(rows)} pages | {len(document):,} chars — calling all three models...")

    results = await asyncio.gather(
        *[CALLERS[key](system_prompt, document) for key, _ in MODELS],
        return_exceptions=True,
    )

    file_cost = 0.0
    for (model_key, model_name), result in zip(MODELS, results):
        if isinstance(result, Exception):
            print(f"  [{model_key}] ERROR: {result}")
            continue
        text, in_tok, out_tok = result
        cost = calc_cost(model_key, in_tok, out_tok)
        file_cost += cost
        url = save_story(pdf_file, model_key, model_name, text, in_tok, out_tok, cost)
        print(f"  [{model_key}] {in_tok:,} in / {out_tok:,} out | ${cost:.4f} -> {url}")

    return file_cost


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    overwrite   = "--overwrite" in sys.argv
    single_file = next((a for a in sys.argv[1:] if not a.startswith("--") and not a.isdigit()), None)

    limit = DEFAULT_BATCH_LIMIT
    if "--limit" in sys.argv:
        idx = sys.argv.index("--limit")
        if idx + 1 < len(sys.argv):
            limit = int(sys.argv[idx + 1])

    system_prompt = PROMPT_FILE.read_text(encoding="utf-8")

    if single_file:
        files = [single_file]
    else:
        files = get_all_transcribed_files()

    # Filter out already-done files unless overwrite
    if not overwrite:
        todo     = [f for f in files if not already_done(f)]
        skipped  = len(files) - len(todo)
        if skipped:
            print(f"Skipping {skipped} already-completed file(s). Use --overwrite to regenerate.")
    else:
        todo = files

    # Apply batch limit (single-file runs are exempt)
    if not single_file and len(todo) > limit:
        print(f"Capping to {limit} of {len(todo)} remaining file(s). Use --limit N to change.")
        todo = todo[:limit]

    if not todo:
        print("Nothing to process.")
        return

    # Cost warning — roughly $0.01–$0.75 per file across all three models
    est_low  = len(todo) * 0.01
    est_high = len(todo) * 0.75
    print(f"\n{'=' * 50}")
    print(f"  Files to process : {len(todo)}")
    print(f"  Estimated cost   : ${est_low:.2f} – ${est_high:.2f}  (all 3 models)")
    print(f"  WARNING: This script is intended for single-file or small-batch use.")
    print(f"           Running at scale can be expensive.")
    print(f"{'=' * 50}")
    answer = input("\nProceed? [y/N] ").strip().lower()
    if answer != "y":
        print("Aborted.")
        return

    sem        = asyncio.Semaphore(2)
    total_cost = 0.0
    lock       = asyncio.Lock()

    async def run(i, pdf_file):
        async with sem:
            cost = await generate_stories_for_file(pdf_file, system_prompt, i, len(todo))
            async with lock:
                nonlocal total_cost
                total_cost += cost

    await asyncio.gather(*[run(i, f) for i, f in enumerate(todo, 1)])

    print(f"\n{'=' * 50}")
    print(f"Total files processed : {len(todo)}")
    print(f"Total cost            : ${total_cost:.4f}")
    print(f"Stories uploaded to   : s3://{S3_BUCKET}/stories/")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    asyncio.run(main())
