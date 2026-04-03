import os
import json
import sqlite3
import time
import requests
from dotenv import load_dotenv

load_dotenv()

NARA_API_KEY = os.getenv("NARA_API_KEY")
BASE_URL = "https://catalog.archives.gov/api/v2"
DB_PATH = "api_requests.db"

HEADERS = {
    "x-api-key": NARA_API_KEY,
    "Content-Type": "application/json",
}

REQUEST_TIMEOUT = 60  # seconds — NARA API is slow, regularly takes 10-12s

# ============================================================================
# DATABASE
# ============================================================================

def init_db():
    """Create api_requests.db and the nara_requests table if they don't exist."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS nara_requests (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            endpoint        TEXT NOT NULL,
            params          TEXT,
            status_code     INTEGER,
            response_ms     INTEGER,
            result_count    INTEGER,
            total_results   INTEGER,
            error_message   TEXT
        )
    """)
    conn.commit()
    return conn


def log_request(conn, endpoint, params, status_code, response_ms,
                result_count=None, total_results=None, error_message=None):
    """Insert a row into nara_requests."""
    conn.execute("""
        INSERT INTO nara_requests
            (endpoint, params, status_code, response_ms, result_count, total_results, error_message)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        endpoint,
        json.dumps(params) if params else None,
        status_code,
        response_ms,
        result_count,
        total_results,
        error_message,
    ))
    conn.commit()


# ============================================================================
# TESTS
# ============================================================================

def test_auth():
    """Confirm API key is loaded from .env."""
    print("\n--- Test 1: API Key Loaded ---")
    if not NARA_API_KEY:
        print("FAIL: NARA_API_KEY not found in .env")
        return False
    print(f"OK:  NARA_API_KEY loaded ({NARA_API_KEY[:6]}...)")
    return True


def nara_get(endpoint, params):
    """Make a GET request to the NARA API, return (response_ms, response_or_None, error_str)."""
    start = time.time()
    try:
        response = requests.get(f"{BASE_URL}{endpoint}", headers=HEADERS, params=params, timeout=REQUEST_TIMEOUT)
        response_ms = int((time.time() - start) * 1000)
        return response_ms, response, None
    except requests.exceptions.ReadTimeout:
        response_ms = int((time.time() - start) * 1000)
        return response_ms, None, f"Timed out after {REQUEST_TIMEOUT}s"


def test_basic_search(conn):
    """Hit the search endpoint — a 200 confirms the key is valid and the API is reachable."""
    print("\n--- Test 2: Basic Search (connectivity + auth) ---")
    endpoint = "/records/search"
    params = {"q": "civil war pension", "limit": 3}

    response_ms, response, error = nara_get(endpoint, params)

    if error:
        log_request(conn, endpoint, params, None, response_ms, error_message=error)
        print(f"FAIL: {error}")
        return False

    print(f"Status: {response.status_code}  ({response_ms}ms)")

    if response.status_code != 200:
        error = f"HTTP {response.status_code}"
        log_request(conn, endpoint, params, response.status_code, response_ms, error_message=error)
        print(f"FAIL: {error}")
        return False

    data = response.json()
    total = data.get("body", {}).get("hits", {}).get("total", {}).get("value")
    hits = data.get("body", {}).get("hits", {}).get("hits", [])

    log_request(conn, endpoint, params, response.status_code, response_ms,
                result_count=len(hits), total_results=total)

    print(f"OK:  fetched {len(hits)} records ({total:,} total match in NARA catalog)")
    return True


def test_usct_search(conn):
    """
    Search for a specific known soldier from the project dataset.
    Narrow query keeps results small and confirms record-level access.
    """
    print("\n--- Test 3: Specific Record Search ---")
    endpoint = "/records/search"
    # Narrow query: USCT pension files in RG 15 (Dept. of Veterans Affairs)
    params = {"q": "colored troops pension certificate", "limit": 3}

    response_ms, response, error = nara_get(endpoint, params)

    if error:
        log_request(conn, endpoint, params, None, response_ms, error_message=error)
        print(f"FAIL: {error}")
        return False

    print(f"Status: {response.status_code}  ({response_ms}ms)")

    if response.status_code != 200:
        error = f"HTTP {response.status_code}"
        log_request(conn, endpoint, params, response.status_code, response_ms, error_message=error)
        print(f"FAIL: {error}")
        return False

    data = response.json()
    hits = data.get("body", {}).get("hits", {}).get("hits", [])
    total = data.get("body", {}).get("hits", {}).get("total", {}).get("value", 0)

    log_request(conn, endpoint, params, response.status_code, response_ms,
                result_count=len(hits), total_results=total)

    print(f"OK:  fetched {len(hits)} records ({total:,} total match in NARA catalog)")
    if hits:
        print("\n     First hit record fields:")
        print(json.dumps(hits[0].get("_source", {}).get("record", {}), indent=6)[:2000])

    return True


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    print("=" * 50)
    print("NARA Catalog API - Connection Test")
    print("=" * 50)

    conn = init_db()
    print(f"Logging requests to: {DB_PATH}")

    results = []
    results.append(test_auth())
    if results[0]:
        results.append(test_basic_search(conn))
        results.append(test_usct_search(conn))

    conn.close()

    print("\n" + "=" * 50)
    passed = sum(1 for r in results if r)
    total = len(results)
    print(f"Result: {passed}/{total} tests passed")
    if passed == total:
        print("NARA API key is working correctly.")
    else:
        print("Some tests failed — check output above.")
    print("=" * 50)
