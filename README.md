# Civil War Pension Files

Tools for scraping and extracting structured data from USCT (United States Colored Troops) Civil War pension files.

## Python Setup

1. Create a virtual environment:
   ```bash
   python -m venv venv
   ```

2. Activate the virtual environment:
   - Windows: `venv\Scripts\activate`
   - Mac/Linux: `source venv/bin/activate`

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Create a `.env` file with your API keys:
   ```
   OPENAI_API_KEY=your_openai_key_here
   ANTHROPIC_API_KEY=your_anthropic_key_here
   ```

## Scripts

### `scraper.py`
Scrapes USCT pension file metadata from the Iowa African American Museum of Iowa digital collections. Downloads PDF files and stores metadata in a SQLite database (`usct_pension_files/pension_data.db`).

**Usage:**
```bash
python scraper.py
```

### `extract_service_data.py`
Extracts structured military service data from pension file descriptions using OpenAI's GPT-5-nano with Structured Outputs. Processes descriptions concurrently and stores extracted data in the database.

**Extracted fields include:**
- Regiment, Company, Rank
- Muster in/out dates and places
- Locations, comrades, family members
- Birth information, enslaver details, plantation info

**Configuration:**
- `BATCH_LIMIT`: Number of items to process (None for all)
- `CONCURRENT_REQUESTS`: Number of parallel API requests (default: 10)
- `RETRY_ERRORS`: Whether to retry failed extractions

**Usage:**
```bash
python extract_service_data.py
```

### `export_to_excel.py`
Exports the database to an Excel file (`pension_data_export.xlsx`). Includes original metadata, extracted service data fields, and cost/token statistics.

**Usage:**
```bash
python export_to_excel.py
```

### `reset_extractions.py`
Interactive utility to clear extraction records from the database. Useful for re-running extractions with updated prompts or models.

**Options:**
- Delete all extraction records
- Delete only completed extractions
- Delete only error extractions

**Usage:**
```bash
python reset_extractions.py
```

### `explore.py`
Utility script for converting PDFs to images and extracting text using Claude Vision API. Supports multiple extraction modes and custom prompts.

**Modes:**
- `export`: Convert PDF pages to images
- `extract`: Extract text from images using Claude
- `extract_pdf`: Extract text directly from PDF

**Usage:**
Edit configuration variables in the script, then run:
```bash
python explore.py
```

### `analyze_descriptions.py`
Simple test script to verify API connections for Anthropic and OpenAI with "Hello World" prompts.  Unused

**Usage:**
```bash
python analyze_descriptions.py
```

## Data Pipeline

1. **Scrape** → `scraper.py` downloads PDFs and metadata
2. **Extract** → `extract_service_data.py` extracts structured fields using AI
3. **Export** → `export_to_excel.py` creates Excel file for analysis

## Database Structure

SQLite database: `usct_pension_files/pension_data.db`

**Tables:**
- `items`: Scraped pension file records with metadata
- `extracted_service_data`: AI-extracted military service information
