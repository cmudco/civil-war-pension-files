import asyncio
import os
import time
import sqlite3
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pdf2image import convert_from_path
import io

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
POPPLER_PATH = os.getenv("POPPLER_PATH")

DB_FILE = "transcriber_db.db"
TRANSCRIPTIONS_DIR = Path("transcriptions")
IMAGES_DIR = Path("images")
BATCH_SIZE = 10
OVERWRITE = False  # If False, skip pages already in DB / already have a txt file

# Gemini 3.1 Pro Preview pricing (USD per 1M tokens)
PRICING = {
    "input":  {"short": 2.00,  "long": 4.00},   # <=200k / >200k tokens
    "output": {"short": 12.00, "long": 18.00},
}
THRESHOLD = 200_000  # tokens


def init_db():
    con = sqlite3.connect(DB_FILE)
    con.execute("""
        CREATE TABLE IF NOT EXISTS transcriptions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at      TEXT NOT NULL,
            pdf_file        TEXT NOT NULL,
            page            INTEGER NOT NULL,
            prompt_name     TEXT NOT NULL,
            prompt_text     TEXT NOT NULL,
            model           TEXT NOT NULL,
            elapsed_seconds REAL,
            input_tokens    INTEGER,
            output_tokens   INTEGER,
            cost_usd        REAL,
            txt_file        TEXT,
            result          TEXT
        )
    """)
    con.commit()
    return con


def log_to_db(con, *, pdf_file, page, prompt_name, prompt_text, model,
              elapsed, in_tok, out_tok, cost, txt_file, result):
    con.execute("""
        INSERT INTO transcriptions
            (created_at, pdf_file, page, prompt_name, prompt_text, model,
             elapsed_seconds, input_tokens, output_tokens, cost_usd, txt_file, result)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.utcnow().isoformat(),
        pdf_file, page, prompt_name, prompt_text, model,
        elapsed, in_tok, out_tok, cost, txt_file, result,
    ))
    con.commit()


def save_txt(pdf_path: Path, page_num: int, text: str) -> Path:
    TRANSCRIPTIONS_DIR.mkdir(exist_ok=True)
    stem = pdf_path.stem.replace(" ", "_")
    txt_path = TRANSCRIPTIONS_DIR / f"{stem}_page{page_num}.txt"
    txt_path.write_text(text or "", encoding="utf-8")
    return txt_path


def save_image(pdf_path: Path, page_num: int, image) -> Path:
    IMAGES_DIR.mkdir(exist_ok=True)
    stem = pdf_path.stem.replace(" ", "_")
    img_path = IMAGES_DIR / f"{stem}_page{page_num}.jpg"
    image.save(str(img_path), format="JPEG", quality=95)
    return img_path


def already_done(con, pdf_file: str, page_num: int) -> bool:
    """Check if this page already exists in DB and has a txt file."""
    row = con.execute(
        "SELECT txt_file FROM transcriptions WHERE pdf_file = ? AND page = ?",
        (pdf_file, page_num)
    ).fetchone()
    if not row:
        return False
    txt_path = Path(row[0]) if row[0] else None
    return txt_path is not None and txt_path.exists()


def calc_cost(input_tokens: int, output_tokens: int) -> float:
    tier = "long" if input_tokens > THRESHOLD else "short"
    input_cost  = (input_tokens  / 1_000_000) * PRICING["input"][tier]
    output_cost = (output_tokens / 1_000_000) * PRICING["output"][tier]
    return input_cost + output_cost


def load_prompt(name: str) -> str:
    prompt_path = Path(__file__).parent / "prompts" / f"{name}.md"
    return prompt_path.read_text(encoding="utf-8")


async def transcribe_page(sem, con, con_lock, pdf_path: Path, page_num: int,
                          image, prompt_text: str, prompt_name: str) -> tuple[int, str]:
    async with sem:
        print(f"  Starting page {page_num}...")
        page_start = time.time()

        img_bytes = io.BytesIO()
        image.save(img_bytes, format="JPEG", quality=95)
        img_bytes.seek(0)

        loop = asyncio.get_event_loop()
        for attempt in range(5):
            try:
                img_bytes.seek(0)
                response = await loop.run_in_executor(
                    None,
                    lambda: client.models.generate_content(
                        model="gemini-3.1-pro-preview",
                        contents=[
                            types.Part.from_bytes(data=img_bytes.read(), mime_type="image/jpeg"),
                            prompt_text,
                        ]
                    )
                )
                break
            except Exception as e:
                if attempt == 4:
                    print(f"  Page {page_num} failed after 5 attempts: {e}", flush=True)
                    raise
                wait = 10 * (attempt + 1)
                print(f"  Page {page_num} error (attempt {attempt+1}/5), retrying in {wait}s: {e}", flush=True)
                await asyncio.sleep(wait)

        elapsed = time.time() - page_start
        usage = response.usage_metadata
        in_tok  = usage.prompt_token_count or 0
        out_tok = usage.candidates_token_count or 0
        cost    = calc_cost(in_tok, out_tok)

        txt_path = save_txt(pdf_path, page_num, response.text or "")

        async with con_lock:
            log_to_db(
                con,
                pdf_file=str(pdf_path),
                page=page_num,
                prompt_name=prompt_name,
                prompt_text=prompt_text,
                model="gemini-3.1-pro-preview",
                elapsed=elapsed,
                in_tok=in_tok,
                out_tok=out_tok,
                cost=cost,
                txt_file=str(txt_path),
                result=response.text,
            )

        print(f"  Page {page_num} done — {elapsed:.1f}s | {in_tok:,} in / {out_tok:,} out | ${cost:.6f} | {txt_path}")
        return page_num, response.text, in_tok, out_tok, cost


async def transcribe_pdf_pages_async(pdf_path: str, pages: list[int] | None = None,
                                     prompt_name: str = "basic-extract") -> dict[int, str]:
    from pypdf import PdfReader

    pdf_path = Path(pdf_path)
    prompt_text = load_prompt(prompt_name).replace("{file_name}", pdf_path.name)

    con = init_db()
    con_lock = asyncio.Lock()

    total_pages = len(PdfReader(str(pdf_path)).pages)
    page_list = pages if pages else list(range(1, total_pages + 1))

    todo = [p for p in page_list if OVERWRITE or not already_done(con, str(pdf_path), p)]
    skipped = len(page_list) - len(todo)
    if skipped:
        print(f"Skipping {skipped} already-completed page(s).", flush=True)
    print(f"Processing {len(todo)} of {total_pages} pages ({BATCH_SIZE} concurrent Gemini calls)...\n", flush=True)

    run_start = time.time()
    sem = asyncio.Semaphore(BATCH_SIZE)
    results = {}
    total_input_tokens = total_output_tokens = 0
    total_cost = 0.0
    loop = asyncio.get_event_loop()

    # Convert pages one at a time sequentially, dispatch Gemini calls async
    pending = []
    for idx, page_num in enumerate(todo, 1):
        print(f"[{idx}/{len(todo)}] Page {page_num} — converting image...", flush=True)
        kwargs = {"pdf_path": str(pdf_path), "dpi": 200, "first_page": page_num, "last_page": page_num}
        if POPPLER_PATH:
            kwargs["poppler_path"] = POPPLER_PATH
        images = await loop.run_in_executor(None, lambda kw=kwargs: convert_from_path(**kw))
        image = images[0]
        save_image(pdf_path, page_num, image)
        print(f"[{idx}/{len(todo)}] Page {page_num} — image saved, queuing Gemini call...", flush=True)
        pending.append(transcribe_page(sem, con, con_lock, pdf_path, page_num, image, prompt_text, prompt_name))

    print(f"\nAll images converted. Waiting for {len(pending)} Gemini calls to finish...\n", flush=True)
    page_results = await asyncio.gather(*pending)

    con.close()

    for page_num, text, in_tok, out_tok, cost in page_results:
        results[page_num] = text
        total_input_tokens  += in_tok
        total_output_tokens += out_tok
        total_cost          += cost

    total_elapsed = time.time() - run_start
    print(f"\n{'─'*40}")
    print(f"TOTALS")
    print(f"  Time:   {total_elapsed:.1f}s")
    print(f"  Tokens: {total_input_tokens:,} in / {total_output_tokens:,} out")
    print(f"  Cost:   ${total_cost:.6f}")
    print(f"{'─'*40}\n")

    return results


def transcribe_pdf_pages(pdf_path: str, pages: list[int] | None = None,
                         prompt_name: str = "basic-extract") -> dict[int, str]:
    return asyncio.run(transcribe_pdf_pages_async(pdf_path, pages, prompt_name))


if __name__ == "__main__":
    files = [
        ("usct_pension_files/A_B/Brown (John) Mustifer Civil War Pension.pdf", None),
        ("usct_pension_files/A_B/Brown Adam Civil War Pension.pdf", None),
        ("usct_pension_files/A_B/Brown George.pdf", None),
        ("usct_pension_files/A_B/Brown Harry Civil War Pension.pdf", None),
        ("usct_pension_files/C_D/Cuthbert Sampson Civil War Pension.pdf", None),
        ("usct_pension_files/C_D/Dulaney Jacob (Jones) Civil War Pension.pdf", None),
        ("usct_pension_files/E_F/Fields Daniel Civil War Pension.pdf", None),
        ("usct_pension_files/E_F/Fripp Alfred Civil War Pension.pdf", None),
        ("usct_pension_files/G_H/Goodwin Robert CIvil War Pension.pdf", None),
        ("usct_pension_files/I_J/Jenkins July Civil War Pension.pdf", None),
        ("usct_pension_files/I_J/Jones William Civil War Pension.pdf", None),
        ("usct_pension_files/K_L/Legare Murray Civil War Pension.pdf", None),
    ]

    for pdf, pages in files:
        print(f"\n{'='*60}")
        print(f"Transcribing: {pdf}")
        print('='*60)
        transcribe_pdf_pages(pdf, pages)
