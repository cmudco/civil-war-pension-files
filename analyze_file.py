from urllib import response
from xmlrpc import client
import anthropic
import openai
from dotenv import load_dotenv
import os
from google import genai
from PIL import Image
from pdf2image import convert_from_path
import io
import base64
from pypdf import PdfReader, PdfWriter


# Load environment variables from .env file
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY")

#Initialize API clients
ant_client = anthropic.Anthropic()
openai_client = openai.OpenAI()
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

# ============================================================================
# CONFIGURATION - Change these variables to control what the script does
# ============================================================================

PDF_FILE = r"usct_pension_files/A_B/Binyard Adam Civil War Pension.pdf"

# ============================================================================
# PDF PAGE EXTRACTION
# ============================================================================

def extract_pdf_page(pdf_path, page_number, output_path=None):
    """
    Extract a single page from a PDF and save it as a new single-page PDF.

    This keeps the page as a PDF (no image conversion), which:
    - Preserves text layers for better OCR
    - Much smaller file size than images
    - No compression/quality loss
    - Works directly with LLM APIs that support PDFs

    Args:
        pdf_path: Path to the source PDF file
        page_number: Page number to extract (1-indexed, so page 1 is the first page)
        output_path: Optional path to save the extracted page. If None, saves as temp file.

    Returns:
        Path to the extracted single-page PDF file

    Example:
        page_pdf = extract_pdf_page("pension.pdf", 3)  # Gets page 3 as PDF
    """
    reader = PdfReader(pdf_path)

    # Validate page number
    if page_number < 1 or page_number > len(reader.pages):
        raise ValueError(f"Page {page_number} out of range. PDF has {len(reader.pages)} pages.")

    # Create writer and add just the requested page (0-indexed internally)
    writer = PdfWriter()
    writer.add_page(reader.pages[page_number - 1])

    # Determine output path
    if output_path is None:
        base_name = os.path.splitext(os.path.basename(pdf_path))[0]
        output_path = f"temp_page_{page_number}_{base_name}.pdf"

    # Write the single-page PDF
    with open(output_path, 'wb') as output_file:
        writer.write(output_file)

    return output_path

def get_pdf_page_count(pdf_path):
    """
    Get the total number of pages in a PDF.

    Args:
        pdf_path: Path to the PDF file

    Returns:
        Number of pages

    Example:
        num_pages = get_pdf_page_count("pension.pdf")
    """
    reader = PdfReader(pdf_path)
    return len(reader.pages)

# ============================================================================
# IMAGE CONVERSION (Optional - if you need images instead of PDFs)
# ============================================================================

def extract_pdf_page_as_image(pdf_path, page_number):
    """
    Extract a single page from a PDF and return it as a PIL Image.
    Note: This converts to image, which is larger. Use extract_pdf_page() instead
    unless you specifically need an image.

    Args:
        pdf_path: Path to the PDF file
        page_number: Page number to extract (1-indexed)

    Returns:
        PIL Image object of the extracted page
    """
    images = convert_from_path(
        pdf_path,
        first_page=page_number,
        last_page=page_number,
        dpi=300
    )
    return images[0]

def image_to_base64(image):
    """
    Convert PIL Image to base64 string for API calls.

    Args:
        image: PIL Image object

    Returns:
        Base64 encoded string
    """
    buffered = io.BytesIO()
    image.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode('utf-8')

def test_apis():
    '''
    Test both Anthropics and OpenAI APIs with a simple Hello World Prompt.
    '''
    message = ant_client.messages.create(
        max_tokens=1024,
        messages=[{
            "content": "Hello, world",
            "role": "user",
        }],
        model="claude-sonnet-4-5-20250929",
    )

    print("ANT RESPONSE:\t\t", message.content[0].text)

    openai_response = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "user",
                "content": "Hello, world"
            }
        ], 
        max_tokens=1024,
    )
    print("OPENAI RESPONSE:\t", openai_response.choices[0].message.content) 

    response = gemini_client.models.generate_content(
        model="gemini-2.0-flash", contents="Hello, world"
    )
    print("GEMINI RESPONSE:\t", response.text)

def call_gemini(prompt, model='gemini-2.0-flash', file_path=None):
    """
    Call Gemini API with a text prompt and optional file.

    Args:
        prompt: Text prompt/question to send to Gemini
        model: Gemini model to use (default: gemini-2.0-flash)
        file_path: Optional path to a file to include as context (PDF, image, etc.)

    Returns:
        Response text from Gemini

    Example:
        # Text only
        response = call_gemini("What is the capital of France?")

        # With file
        response = call_gemini("What is in this document?", file_path="page_1.pdf")
    """
    if file_path:
        # Upload file and include in request
        uploaded_file = gemini_client.files.upload(file=file_path)
        contents = [uploaded_file, prompt]
    else:
        # Text only
        contents = prompt

    response = gemini_client.models.generate_content(
        model=model,
        contents=contents
    )

    return response.text


if __name__ == "__main__":
    # Example: Extract page 1 from a pension file
    pdf_file = r"usct_pension_files/A_B/Binyard Adam Civil War Pension.pdf"
    page_num = 4

    # Get total page count first
    total_pages = get_pdf_page_count(pdf_file)
    print(f"PDF has {total_pages} pages total")

    print(f"\nExtracting page {page_num} from PDF...")
    page_pdf_path = extract_pdf_page(pdf_file, page_num)

    response = call_gemini("", file_path=page_pdf_path)  
    print("GEMINI RESPONSE:\t", response)

    