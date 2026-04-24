import os
import sqlite3
import pandas as pd
import weaviate
import time
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from weaviate.classes.init import Auth
from weaviate.classes.query import Filter
from dotenv import load_dotenv
from google import genai
from google.genai import types

from names.names_utils import build_master_list

load_dotenv()

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(ROOT_DIR, "transcriber_db.db")

# --- CONFIGURATION ---
genai_client = genai.Client(
    api_key=os.getenv("GOOGLE_API_KEY"),
    http_options={'api_version': 'v1beta'}
)

EMBEDDING_MODEL = "gemini-embedding-2-preview"
GENERATION_MODEL = "gemini-2.5-flash"
BATCH_LIMIT = 10
CHUNK_LIMIT = 15

def get_embedding_with_retry(text, retries=5):
    for i in range(retries):
        try:
            result = genai_client.models.embed_content(model=EMBEDDING_MODEL, contents=text)
            return result.embeddings[0].values
        except Exception as e:
            if any(err in str(e).lower() for err in ["429", "quota", "503"]):
                time.sleep((i + 1) * 3)
            else:
                return None
    return None

def extract_bio_from_file(weaviate_client, name, file_name):
    collection = weaviate_client.collections.get("CivilWarPensionPage")
    query_vector = get_embedding_with_retry(f"{name} biography birth slaveholder marriage family")
    if not query_vector:
        return None

    try:
        response = collection.query.near_vector(
            near_vector=query_vector, limit=CHUNK_LIMIT, filters=Filter.by_property("pdf_file").equal(file_name)
        )
    except Exception:
        return None

    context = "\n\n".join([(obj.properties.get('text') or "")[:2000] for obj in response.objects])

    prompt = f"""
    You are extracting strictly factual biographical data from historical pension files.
    Target Entity: '{name}'
    Source File: {file_name}
    
    CRITICAL: Ignore the primary soldiers if '{name}' is a secondary witness or enslaver. 
    ONLY extract information if it relates directly to '{name}'.
    
    Extract these 4 data points. Keep text highly concise. If missing, output null.
    1. birth_age: Exact year or relative timeframe.
    2. slaveholder_info: Enslaver names, locations, dates.
    3. marriage_info: Spouse name, marriage date/location.
    4. family_members: Parents, siblings, children.
    
    Return ONLY valid JSON.
    {{
        "birth_age": "...", "slaveholder_info": "...", "marriage_info": "...", "family_members": "..."
    }}
    
    Text: {context}
    """

    for attempt in range(3):
        try:
            res = genai_client.models.generate_content(
                model=GENERATION_MODEL, contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.1)
            )
            return json.loads(res.text)
        except Exception as e:
            if any(err in str(e).lower() for err in ["429", "quota", "503"]):
                time.sleep((attempt + 1) * 5)
            else:
                return None
    return None

def run_extraction_pipeline(master_df=None):
    print("\n[STEP 2] AI Bio Extraction")
    print("=" * 50)
    
    if master_df is None:
        master_df = build_master_list(DB_PATH)

    if master_df.empty:
        return master_df

    # --- BATCH CONTROL ---
    missing_tasks = master_df[~master_df['gemini_extracted'].astype(str).isin(['1', '1.0'])].head(BATCH_LIMIT)

    if missing_tasks.empty:
        print("  [SKIP] All profiles already extracted.")
        return

    client = weaviate.connect_to_custom(
        http_host="weaviate.hss.cmu.edu", http_port=443, http_secure=True,
        grpc_host="grpc-weaviate.hss.cmu.edu", grpc_port=443, grpc_secure=True,
        auth_credentials=Auth.api_key(os.getenv("WEAVIATE_KEY"))
    )

    try:
        print(f"  [RUN] Extracting {len(missing_tasks)} profiles via Gemini...")
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_row = {executor.submit(extract_bio_from_file, client, row['canonical_name'], row['pdf_file']): row for _, row in missing_tasks.iterrows()}

            for future in as_completed(future_to_row):
                row = future_to_row[future]
                try:
                    data = future.result()
                    if data:
                        cursor.execute("""
                            UPDATE persons 
                            SET birth_age = ?, slaveholder_info = ?, marriage_info = ?, family_members = ?, gemini_extracted = '1'
                            WHERE cluster_id = ?
                        """, (data.get('birth_age'), data.get('slaveholder_info'),
                              data.get('marriage_info'), data.get('family_members'), row['cluster_id']))
                        conn.commit()
                        print(f"    + {row['canonical_name']}")
                except Exception as e:
                    print(f"    ! {row['canonical_name']}: {e}")
        conn.close()
    finally:
        client.close()

    return build_master_list(DB_PATH)

if __name__ == "__main__":
    run_extraction_pipeline()
