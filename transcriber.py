import os
import time
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pdf2image import convert_from_path
import io

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
POPPLER_PATH = os.getenv("POPPLER_PATH")

# Gemini 3.1 Pro Preview pricing (USD per 1M tokens)
PRICING = {
    "input":  {"short": 2.00,  "long": 4.00},   # <=200k / >200k tokens
    "output": {"short": 12.00, "long": 18.00},
}
THRESHOLD = 200_000  # tokens


def calc_cost(input_tokens: int, output_tokens: int) -> float:
    tier = "long" if input_tokens > THRESHOLD else "short"
    input_cost  = (input_tokens  / 1_000_000) * PRICING["input"][tier]
    output_cost = (output_tokens / 1_000_000) * PRICING["output"][tier]
    return input_cost + output_cost


def load_prompt(name: str) -> str:
    prompt_path = Path(__file__).parent / "prompts" / f"{name}.md"
    return prompt_path.read_text(encoding="utf-8")


def transcribe_pdf_pages(pdf_path: str, pages: list[int] | None = None) -> dict[int, str]:
    """
    Transcribe pages from a PDF file using Gemini.

    Args:
        pdf_path: Path to the PDF file
        pages: List of 1-based page numbers to process. If None, processes all pages.

    Returns:
        Dict mapping page number to transcribed text.
    """
    pdf_path = Path(pdf_path)
    prompt_text = load_prompt("basic-extract").replace("{file_name}", pdf_path.name)

    kwargs = {"pdf_path": str(pdf_path), "dpi": 200}
    if POPPLER_PATH:
        kwargs["poppler_path"] = POPPLER_PATH
    if pages:
        kwargs["first_page"] = min(pages)
        kwargs["last_page"] = max(pages)

    images = convert_from_path(**kwargs)

    start_page = min(pages) if pages else 1
    results = {}

    total_input_tokens = 0
    total_output_tokens = 0
    total_cost = 0.0
    run_start = time.time()

    for i, image in enumerate(images):
        page_num = start_page + i
        if pages and page_num not in pages:
            continue

        print(f"Transcribing page {page_num}...")
        page_start = time.time()

        img_bytes = io.BytesIO()
        image.save(img_bytes, format="JPEG", quality=95)
        img_bytes.seek(0)

        response = client.models.generate_content(
            model="gemini-3.1-pro-preview",
            contents=[
                types.Part.from_bytes(data=img_bytes.read(), mime_type="image/jpeg"),
                prompt_text,
            ]
        )

        elapsed = time.time() - page_start
        usage = response.usage_metadata
        in_tok  = usage.prompt_token_count or 0
        out_tok = usage.candidates_token_count or 0
        cost    = calc_cost(in_tok, out_tok)

        total_input_tokens  += in_tok
        total_output_tokens += out_tok
        total_cost          += cost

        print(f"  Time:   {elapsed:.1f}s")
        print(f"  Tokens: {in_tok:,} in / {out_tok:,} out")
        print(f"  Cost:   ${cost:.6f}")

        results[page_num] = response.text

    total_elapsed = time.time() - run_start
    print(f"\n{'─'*40}")
    print(f"TOTALS")
    print(f"  Time:   {total_elapsed:.1f}s")
    print(f"  Tokens: {total_input_tokens:,} in / {total_output_tokens:,} out")
    print(f"  Cost:   ${total_cost:.6f}")
    print(f"{'─'*40}\n")

    return results


if __name__ == "__main__":
    pdf = "usct_pension_files/A_B/Abbs Wilkins.pdf"
    pages = [3]

    transcriptions = transcribe_pdf_pages(pdf, pages)

    for page_num, text in sorted(transcriptions.items()):
        print(f"\n{'='*60}")
        print(f"PAGE {page_num}")
        print('='*60)
        print(text)
