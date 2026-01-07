# USCT Pension Files Downloader

Carnegie Mellon University Dietrich College research project for downloading and analyzing Civil War pension application files from the Iowa African American Museum (IAAM) Omeka S collection.

## Features

- **Polite Scraping**: Configurable random delays between requests (default: 2-10 seconds)
- **SQLite Persistence**: All metadata and download status tracked in database
- **Resume Support**: Automatically resumes interrupted downloads
- **Progress Tracking**: Nested progress bars with ETA and speed indicators
- **Comprehensive Logging**: Dual logging to file and console, critical events logged to database
- **Professional User-Agent**: Identifies research project and contact information

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/civil-war-pension-files.git
cd civil-war-pension-files

# Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

## Usage

### Basic Download

Download all pension files from all letter ranges:

```bash
python scraper.py
```

### Resume Interrupted Download

Simply run the same command again. The scraper automatically detects completed items and resumes where it left off:

```bash
python scraper.py
```

### Custom Delays (Be Polite!)

Adjust the random delay range between requests:

```bash
python scraper.py --min-delay 5 --max-delay 15
```

This sets random delays between 5-15 seconds (average ~10 seconds per request).

### Test with Limited Items

Download only a few items for testing:

```bash
python scraper.py --limit 10 --min-delay 1 --max-delay 2
```

### Process Specific Letter Range

Download only a specific alphabetical range:

```bash
python scraper.py --set "A-B"
```

### Command-Line Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--limit` | int | None | Maximum number of items to download (for testing) |
| `--set` | str | None | Only process specific letter range (e.g., 'A-B', 'C-D') |
| `--min-delay` | float | 2.0 | Minimum seconds between requests |
| `--max-delay` | float | 10.0 | Maximum seconds between requests |

## Database

All data is stored in `usct_pension_files/pension_data.db` with three main tables:

### Tables

**items**: Pension application metadata
- `id` - Omeka item ID (primary key)
- `title` - Item title
- `surname` - Applicant surname
- `item_set_id` - Which letter range collection
- `letter_range` - Human-readable range (A-B, C-D, etc.)
- `metadata` - Full metadata as JSON
- `status` - 'pending', 'in_progress', 'completed', 'error'
- `date_processed` - When item was processed
- `date_modified` - Last modification

**files**: Downloaded PDF files tracking
- `id` - Auto-increment primary key
- `item_id` - Foreign key to items table
- `media_id` - Omeka media ID (unique)
- `filename` - Local filename
- `file_path` - Relative path from output directory
- `file_size` - Size in bytes
- `status` - 'pending', 'downloaded', 'exists', 'error'
- `download_date` - When file was downloaded
- `url` - Original download URL

**logs**: Critical events and errors
- `id` - Auto-increment primary key
- `timestamp` - When event occurred
- `level` - 'INFO', 'WARNING', 'ERROR'
- `message` - Log message
- `item_id` - Optional reference to item
- `media_id` - Optional reference to media

### Querying the Database

Use SQLite command-line tool or any SQLite browser:

```bash
# Open database
sqlite3 usct_pension_files/pension_data.db

# Count completed items
SELECT COUNT(*) FROM items WHERE status='completed';

# Find items with errors
SELECT id, title, error_message FROM items WHERE status='error';

# List all downloaded files
SELECT i.title, f.filename, f.file_size
FROM files f
JOIN items i ON f.item_id = i.id
WHERE f.status='downloaded';

# Check recent errors
SELECT timestamp, level, message
FROM logs
WHERE level='ERROR'
ORDER BY timestamp DESC
LIMIT 10;

# Get statistics by letter range
SELECT letter_range, COUNT(*) as total,
       SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) as completed
FROM items
GROUP BY letter_range;
```

## Logging

The scraper maintains two types of logs:

### File Log

Detailed operation log: `usct_pension_files/scraper.log`

Contains all INFO, WARNING, and ERROR messages with timestamps.

### Database Log

Critical events: `logs` table in database

Only WARNING and ERROR level messages are logged to the database for queryability.

### Console Output

Real-time progress:
- Outer progress bar shows progress through item sets (A-B, C-D, etc.)
- Inner progress bar shows progress through items within current set
- INFO level messages about major operations
- Final statistics summary

## Project Structure

```
civil-war-pension-files/
├── scraper.py                 # Main scraper script
├── requirements.txt           # Python dependencies
├── README.md                  # This file
├── .env.example              # Environment variables template
└── usct_pension_files/       # Output directory
    ├── pension_data.db       # SQLite database
    ├── scraper.log           # Detailed log file
    ├── A_B/                  # Downloaded PDFs by letter range
    ├── C_D/
    └── ...
```

## User-Agent

The scraper identifies itself with a professional User-Agent header:

```
USCT-Pension-Downloader/1.0 (Carnegie Mellon University Dietrich College research project; contact: gdcann@andrew.cmu.edu)
```

This helps the IAAM server administrators understand the nature of the requests and provides a contact point if needed.

## Technical Details

### Rate Limiting

- Random delays between all requests (default 2-10 seconds)
- Additional delays on retry attempts
- Configurable via `--min-delay` and `--max-delay`
- Average request rate: ~5-6 requests per minute (very polite)

### Resume Functionality

The scraper tracks completion status in the database:
1. Items marked 'completed' are automatically skipped
2. Files marked 'downloaded' in database are not re-downloaded
3. Filesystem check ensures files that exist on disk are not re-downloaded
4. Safe to Ctrl+C and restart at any time

### Error Handling

- Automatic retry with exponential backoff for network errors
- Individual item failures don't stop the entire scrape
- All errors logged to both file and database
- Items with errors can be re-attempted by updating database status

### Windows Compatibility

- Uses SQLite WAL (Write-Ahead Logging) mode for better Windows support
- Path handling via `pathlib` for cross-platform compatibility
- File encoding explicitly set to UTF-8

## Performance

### Estimated Runtime

With default settings (2-10 second delays):
- ~1000 items with 2 files each
- Average 6 seconds per request
- ~3-5 hours total runtime

For faster testing, use shorter delays:
```bash
python scraper.py --min-delay 1 --max-delay 3 --limit 50
```

### Disk Space

- Each PDF ranges from ~1MB to ~50MB
- Total collection size: varies by letter range
- Ensure adequate disk space before starting full download

## Troubleshooting

### Database Locked Error

If you see "database is locked" errors:
1. Ensure only one instance of the scraper is running
2. Check that no other program is accessing the database
3. Database uses WAL mode which should prevent this, but SQLite can still lock on Windows

### Progress Bar Issues

If progress bars don't display correctly:
- Use a terminal that supports ANSI escape codes
- On Windows, use Windows Terminal or PowerShell (not cmd.exe)
- Check that tqdm is properly installed

### Network Timeouts

If you encounter frequent timeouts:
1. Check your internet connection
2. The server might be experiencing issues
3. Try again later or increase the `--min-delay` to be more polite

### Resuming from Specific Point

To restart a specific letter range:
```bash
# Clear completed status for a letter range
sqlite3 usct_pension_files/pension_data.db
UPDATE items SET status='pending' WHERE letter_range='A-B';

# Then run scraper for that set
python scraper.py --set "A-B"
```

## Contributing

This is a research project. If you find bugs or have suggestions:
1. Check the logs in `usct_pension_files/scraper.log`
2. Check the database for error details
3. Contact: gdcann@andrew.cmu.edu

## Citation

If you use this data in your research, please cite:
- Iowa African American Museum (IAAM) Omeka S collection
- Carnegie Mellon University Dietrich College

## License

Please respect the original materials and the IAAM's terms of use.

## Contact

Project Contact: gdcann@andrew.cmu.edu
Carnegie Mellon University Dietrich College
