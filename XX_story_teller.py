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
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from google import genai
from google.genai import types
from openai import AsyncOpenAI

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DB_FILE     = "transcriber_db.db"
STORIES_DIR = Path("stories")
PROMPT_FILE = Path(__file__).parent / "prompts" / "story-teller.md"

GEMINI_MODEL    = "gemini-3.1-pro-preview"
OPENAI_MODEL    = "gpt-5.4"
ANTHROPIC_MODEL = "claude-opus-4-6"

# Gemini max output: 65,536 | OpenAI: 128,000 | Anthropic: 128,000
MAX_OUTPUT_TOKENS = 16_384

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
# Output path
# ---------------------------------------------------------------------------

def story_folder(pdf_file: str) -> Path:
    stem = Path(pdf_file).stem.replace(" ", "_")
    return STORIES_DIR / stem


def already_done(pdf_file: str) -> bool:
    folder = story_folder(pdf_file)
    return all((folder / f"{key}.md").exists() for key, _ in MODELS)


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
               text: str, in_tok: int, out_tok: int, cost: float) -> Path:
    folder = story_folder(pdf_file)
    folder.mkdir(parents=True, exist_ok=True)
    out_path = folder / f"{model_key}.md"

    header = (
        f"# {Path(pdf_file).stem}\n\n"
        f"**Model:** `{model_name}`  \n"
        f"**Generated:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}  \n"
        f"**Tokens:** {in_tok:,} in / {out_tok:,} out  \n"
        f"**Cost:** ${cost:.4f}  \n\n"
        f"---\n\n"
    )
    out_path.write_text(header + (text or ""), encoding="utf-8")
    return out_path


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
        path = save_story(pdf_file, model_key, model_name, text, in_tok, out_tok, cost)
        print(f"  [{model_key}] {in_tok:,} in / {out_tok:,} out | ${cost:.4f} -> {path}")

    return file_cost


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    overwrite   = "--overwrite" in sys.argv
    single_file = next((a for a in sys.argv[1:] if not a.startswith("--")), None)

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

    print(f"Files to process: {len(todo)}")

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
    print(f"Stories saved to      : {STORIES_DIR}/")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    asyncio.run(main())
