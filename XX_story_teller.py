"""
XX_story_teller.py

Generates a narrative story report for a single pension file using
Gemini, OpenAI, and Anthropic in parallel. Each model produces its
own .md file in the stories/ directory.

Usage:
    python XX_story_teller.py
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

# Gemini max output: 65,536 | OpenAI max output: 128,000 | Anthropic max output: 128,000
# Using a shared ceiling that fits all three and is more than enough for a thorough narrative
MAX_OUTPUT_TOKENS = 16_384

# Pricing per 1M tokens
PRICING = {
    "gemini":    {"input": 2.00,  "output": 12.00},  # <= 200k input tier
    "openai":    {"input": 2.50,  "output": 15.00},
    "anthropic": {"input": 5.00,  "output": 25.00},
}

# Default test file — override via CLI argument
DEFAULT_FILE = "usct_pension_files/A_B/Brown Adam Civil War Pension.pdf"


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------

def load_transcriptions(pdf_file: str) -> list[dict]:
    con = sqlite3.connect(DB_FILE)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT page, result FROM transcriptions "
        "WHERE pdf_file = ? AND result IS NOT NULL "
        "ORDER BY page",
        (pdf_file,)
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def build_document(rows: list[dict]) -> str:
    parts = [f"=== PAGE {r['page']} ===\n{r['result']}" for r in rows]
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Cost
# ---------------------------------------------------------------------------

def calc_cost(model_key: str, input_tokens: int, output_tokens: int) -> float:
    p = PRICING[model_key]
    return (input_tokens / 1_000_000) * p["input"] + (output_tokens / 1_000_000) * p["output"]


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
            config=types.GenerateContentConfig(
                max_output_tokens=MAX_OUTPUT_TOKENS,
            ),
        )
    )
    usage   = response.usage_metadata
    in_tok  = usage.prompt_token_count or 0
    out_tok = usage.candidates_token_count or 0
    return response.text, in_tok, out_tok


async def call_openai(system_prompt: str, document: str) -> tuple[str, int, int]:
    client   = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    response = await client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": document},
        ],
        max_completion_tokens=MAX_OUTPUT_TOKENS,
    )
    in_tok  = response.usage.prompt_tokens
    out_tok = response.usage.completion_tokens
    return response.choices[0].message.content, in_tok, out_tok


async def call_anthropic(system_prompt: str, document: str) -> tuple[str, int, int]:
    client   = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    response = await client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": document}],
    )
    in_tok  = response.usage.input_tokens
    out_tok = response.usage.output_tokens
    text    = "".join(b.text for b in response.content if hasattr(b, "text"))
    return text, in_tok, out_tok


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------

def save_story(pdf_file: str, model_key: str, model_name: str,
               text: str, in_tok: int, out_tok: int, cost: float) -> Path:
    STORIES_DIR.mkdir(exist_ok=True)
    stem     = Path(pdf_file).stem.replace(" ", "_")
    out_path = STORIES_DIR / f"{stem}__{model_key}.md"

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
# Entry point
# ---------------------------------------------------------------------------

async def generate_stories(pdf_file: str):
    print(f"File : {pdf_file}")

    rows = load_transcriptions(pdf_file)
    if not rows:
        print("No transcriptions found in DB for this file. Run 01_transcriber.py first.")
        return

    document      = build_document(rows)
    system_prompt = PROMPT_FILE.read_text(encoding="utf-8")

    print(f"Pages : {len(rows)}")
    print(f"Chars : {len(document):,}")
    print(f"\nCalling Gemini, OpenAI, and Anthropic in parallel...\n")

    results = await asyncio.gather(
        call_gemini(system_prompt, document),
        call_openai(system_prompt, document),
        call_anthropic(system_prompt, document),
        return_exceptions=True,
    )

    configs = [
        ("gemini",    GEMINI_MODEL),
        ("openai",    OPENAI_MODEL),
        ("anthropic", ANTHROPIC_MODEL),
    ]

    print(f"{'Model':<12} {'In tokens':>10} {'Out tokens':>11} {'Cost':>8}  Output file")
    print("-" * 90)

    for (model_key, model_name), result in zip(configs, results):
        if isinstance(result, Exception):
            print(f"  {model_key:<10} ERROR: {result}")
            continue

        text, in_tok, out_tok = result
        cost = calc_cost(model_key, in_tok, out_tok)
        path = save_story(pdf_file, model_key, model_name, text, in_tok, out_tok, cost)
        print(f"  {model_key:<10} {in_tok:>10,} {out_tok:>11,} {cost:>8.4f}  {path}")

    print("\nDone.")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_FILE
    asyncio.run(generate_stories(target))
