from dotenv import load_dotenv
import os
import platform
import anthropic

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
POPPLER_PATH = os.getenv("POPPLER_PATH")

IS_WINDOWS = os.name == "nt" or platform.system().lower() == "windows"
print(f"Running on Windows: {IS_WINDOWS}")
print(f"POPPLER_PATH: {POPPLER_PATH}")

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY is not set in environment variables.")
if not ANTHROPIC_API_KEY:
    raise ValueError("ANTHROPIC_API_KEY is not set in environment variables.")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY is not set in environment variables.")
if not POPPLER_PATH and IS_WINDOWS:
    raise ValueError("POPPLER_PATH is not set in environment variables. This is required for Windows systems.")

from pdf2image import convert_from_path
import base64
from PIL import Image
import io
import sys

# ============================================================================
# CONFIGURATION - Change these variables to control what the script does
# ============================================================================
MODE = "extract"  # "export" to convert PDF to images, "extract" to extract text from image, "extract_pdf" to extract text from PDF

# For export mode:
PDF_PATH = r"pension-files/scott-joseph/Scott-Joseph.pdf"
PAGE_NUMBER = 3  # Which page to export (1-indexed)

# For extract mode:
IMAGE_PATH = r"outputs/images/scott-joseph/page_3.png"

# For extract_pdf mode:
PDF_PATH_FOR_EXTRACTION = r"pension-files/scott-joseph/Scott-Joseph Page 01.pdf"

# Output directory for exported images
OUTPUT_DIR = r"outputs/images/scott-joseph"

# Prompt file path (markdown file containing LLM extraction instructions)
PROMPT_FILE = r"prompts/basic-extract.md"
# ============================================================================

def load_prompt_from_file(prompt_file_path):
    """Load prompt text from a markdown file"""
    try:
        with open(prompt_file_path, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except FileNotFoundError:
        print(f"Warning: Prompt file not found at {prompt_file_path}")
        print("Using default prompt instead.")
        return "Please extract all text from this document, preserving the original structure and formatting."

def export_pdf_to_images(pdf_path, output_dir, page_number=None):
    """Convert PDF page to image"""
    print(f"Converting PDF: {pdf_path}")

    if page_number:
        print(f"Extracting page {page_number}...")
        images = convert_from_path(
            pdf_path,
            first_page=page_number,
            last_page=page_number,
            poppler_path=POPPLER_PATH if IS_WINDOWS else None
        )
    else:
        images = convert_from_path(pdf_path, poppler_path=POPPLER_PATH if IS_WINDOWS else None)

    # Create output directory
    pdf_name = pdf_path.split('/')[-1].replace('.pdf', '').replace('-', '_').lower()
    image_output_dir = f"{output_dir}/images/{pdf_name}"
    os.makedirs(image_output_dir, exist_ok=True)

    # Save page(s)
    for i, image in enumerate(images):
        actual_page = page_number if page_number else i + 1
        image_path = f"{image_output_dir}/page_{actual_page}.png"
        image.save(image_path, 'PNG')
        print(f"Saved: {image_path}")

    print(f"\nExported {len(images)} page(s) to {image_output_dir}")

def prepare_image_for_claude(image_path):
    """Load, resize, and compress image to meet Claude API requirements"""
    img = Image.open(image_path)
    print(f"Original image size: {img.size}")

    # Claude API has max dimension of 8000 pixels - resize if needed
    max_dimension = 8000
    if max(img.size) > max_dimension:
        ratio = max_dimension / max(img.size)
        new_size = tuple(int(dim * ratio) for dim in img.size)
        img = img.resize(new_size, Image.Resampling.LANCZOS)
        print(f"Resized to fit 8000px limit: {img.size}")

    # Try with high quality JPEG
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='JPEG', quality=95)
    img_byte_arr = img_byte_arr.getvalue()
    print(f"At quality 95: {len(img_byte_arr) / 1024 / 1024:.2f} MB")

    # If over 5MB, iteratively reduce until under limit
    # Note: base64 encoding adds ~33% overhead, so we need to target 3.7MB to stay under 5MB after encoding
    target_size = 3.7 * 1024 * 1024
    if len(img_byte_arr) > target_size:
        print("Reducing to fit under 5MB...")

        # Try reducing quality first
        for quality in [90, 85, 80, 75]:
            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format='JPEG', quality=quality)
            img_byte_arr = img_byte_arr.getvalue()
            print(f"Quality {quality}: {len(img_byte_arr) / 1024 / 1024:.2f} MB")
            if len(img_byte_arr) <= target_size:
                break

        # If still too big, resize
        if len(img_byte_arr) > target_size:
            for max_dim in [7500, 7000, 6500, 6000, 5500, 5000]:
                ratio = max_dim / max(img.size)
                new_size = tuple(int(dim * ratio) for dim in img.size)
                resized_img = img.resize(new_size, Image.Resampling.LANCZOS)
                img_byte_arr = io.BytesIO()
                resized_img.save(img_byte_arr, format='JPEG', quality=90)
                img_byte_arr = img_byte_arr.getvalue()
                print(f"Resized to {new_size}, quality 90: {len(img_byte_arr) / 1024 / 1024:.2f} MB")
                if len(img_byte_arr) <= target_size:
                    img = resized_img
                    break

    print(f"Final image size: {len(img_byte_arr)} bytes ({len(img_byte_arr) / 1024 / 1024:.2f} MB)")

    # Encode to base64
    image_data = base64.standard_b64encode(img_byte_arr).decode("utf-8")
    return image_data

def extract_text_from_image(image_path):
    """Send image to Claude and extract text"""
    print(f"\nProcessing image: {image_path}\n")

    # Load prompt from file
    prompt = load_prompt_from_file(PROMPT_FILE)

    # Prepare image
    image_data = prepare_image_for_claude(image_path)

    # Call Claude API
    ant_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = ant_client.messages.create(
        model="claude-opus-4-5",
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": image_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ],
            }
        ],
    )

    # Print extracted text
    print("\n" + "="*80)
    print("EXTRACTED TEXT:")
    print("="*80)
    print(message.content[0].text)
    print("="*80)

def extract_text_from_pdf(pdf_path):
    """Send PDF to Claude and extract text"""
    print(f"\nProcessing PDF: {pdf_path}\n")

    # Load prompt from file
    prompt = load_prompt_from_file(PROMPT_FILE)

    # Read PDF file and encode to base64
    with open(pdf_path, 'rb') as pdf_file:
        pdf_data = base64.standard_b64encode(pdf_file.read()).decode("utf-8")

    # Get file size
    file_size = os.path.getsize(pdf_path)
    print(f"PDF file size: {file_size / 1024 / 1024:.2f} MB")

    # Call Claude API
    ant_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = ant_client.messages.create(
        model="claude-opus-4-5",
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ],
            }
        ],
    )

    # Print extracted text
    print("\n" + "="*80)
    print("EXTRACTED TEXT:")
    print("="*80)
    print(message.content[0].text)
    print("="*80)

# Run based on MODE setting
if __name__ == "__main__":
    if MODE == "export":
        export_pdf_to_images(PDF_PATH, OUTPUT_DIR, PAGE_NUMBER)
    elif MODE == "extract":
        extract_text_from_image(IMAGE_PATH)
    elif MODE == "extract_pdf":
        extract_text_from_pdf(PDF_PATH_FOR_EXTRACTION)
    else:
        print(f"Invalid MODE: {MODE}. Must be 'export', 'extract', or 'extract_pdf'")
