import os
import sqlite3
from pathlib import Path
from dotenv import load_dotenv
from pdf2image import convert_from_path

load_dotenv()

POPPLER_PATH = os.getenv("POPPLER_PATH")
DB_FILE = "transcriber_db.db"
IMAGES_DIR = Path("images")


def already_done(pdf_path: Path, page_num: int) -> bool:
    stem = pdf_path.stem.replace(" ", "_")
    return (IMAGES_DIR / f"{stem}_page{page_num}.jpg").exists()


def generate_images_for_pdf(pdf_path: Path, pages: list[int]):
    kwargs = {"pdf_path": str(pdf_path), "dpi": 200}
    if POPPLER_PATH:
        kwargs["poppler_path"] = POPPLER_PATH
    kwargs["first_page"] = min(pages)
    kwargs["last_page"] = max(pages)

    images = convert_from_path(**kwargs)
    start_page = min(pages)

    for i, image in enumerate(images):
        page_num = start_page + i
        if page_num not in pages:
            continue
        stem = pdf_path.stem.replace(" ", "_")
        img_path = IMAGES_DIR / f"{stem}_page{page_num}.jpg"
        image.save(str(img_path), format="JPEG", quality=95)

    print(f"  Saved {len(pages)} images for {pdf_path.name}")


def main():
    IMAGES_DIR.mkdir(exist_ok=True)

    con = sqlite3.connect(DB_FILE)
    rows = con.execute(
        "SELECT pdf_file, page FROM transcriptions ORDER BY pdf_file, page"
    ).fetchall()
    con.close()

    # Group by pdf_file, skipping pages that already have an image
    by_file: dict[str, list[int]] = {}
    skipped = 0
    for pdf_file, page in rows:
        pdf_path = Path(pdf_file)
        if already_done(pdf_path, page):
            skipped += 1
            continue
        by_file.setdefault(pdf_file, []).append(page)

    if skipped:
        print(f"Skipping {skipped} pages that already have images.")
    print(f"Generating images for {sum(len(p) for p in by_file.values())} pages across {len(by_file)} files...\n")

    for pdf_file, pages in by_file.items():
        pdf_path = Path(pdf_file)
        print(f"Processing: {pdf_path.name} ({len(pages)} pages)")
        generate_images_for_pdf(pdf_path, pages)

    print("\nDone.")


if __name__ == "__main__":
    main()
