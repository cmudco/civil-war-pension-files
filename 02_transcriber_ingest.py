import asyncio
import os
import re
import sqlite3
from pathlib import Path
from dotenv import load_dotenv
from google import genai
import weaviate
from weaviate.auth import AuthApiKey
from weaviate.classes.config import Configure, Property, DataType, VectorDistances
from weaviate.classes.query import Filter

load_dotenv()

DB_FILE           = "transcriber_db.db"
COLLECTION_NAME   = "CivilWarPensionPage"
EMBEDDING_MODEL   = "gemini-embedding-001"
MAX_CHUNK_CHARS   = 5000
CHUNK_OVERLAP     = 400
PAGE_CONCURRENCY  = 5
EMBED_CONCURRENCY = 10
SLEEP_BETWEEN_EMBEDS = 0.2
WEAVIATE_HTTP_PORT   = 443
WEAVIATE_GRPC_PORT   = 443
OVERWRITE         = False  # If True, re-ingest pages already in Weaviate
NUKE_AND_RECREATE = False  # If True, drop and recreate the entire collection before ingesting
LIMIT             = None   # Set to int to cap pages processed


# ---------------------------------------------------------------------------
# Weaviate
# ---------------------------------------------------------------------------

def connect_weaviate() -> weaviate.WeaviateClient:
    return weaviate.connect_to_custom(
        http_host=os.getenv("WEAVIATE_URL"),
        http_port=WEAVIATE_HTTP_PORT,
        http_secure=True,
        grpc_host=os.getenv("WEAVIATE_GRPC_URL"),
        grpc_port=WEAVIATE_GRPC_PORT,
        grpc_secure=True,
        auth_credentials=AuthApiKey(os.getenv("WEAVIATE_KEY")),
    )


def ensure_collection(client: weaviate.WeaviateClient):
    if NUKE_AND_RECREATE and client.collections.exists(COLLECTION_NAME):
        client.collections.delete(COLLECTION_NAME)
        print(f"Deleted Weaviate collection: {COLLECTION_NAME}")
    if client.collections.exists(COLLECTION_NAME):
        return
    client.collections.create(
        name=COLLECTION_NAME,
        vectorizer_config=Configure.Vectorizer.none(),
        vector_index_config=Configure.VectorIndex.hnsw(distance_metric=VectorDistances.COSINE),
        properties=[
            Property(name="text",             data_type=DataType.TEXT),
            Property(name="transcription_id", data_type=DataType.INT),
            Property(name="pdf_file",         data_type=DataType.TEXT),
            Property(name="pdf_stem",         data_type=DataType.TEXT),
            Property(name="page",             data_type=DataType.INT),
            Property(name="chunk_index",      data_type=DataType.INT),
            Property(name="total_chunks",     data_type=DataType.INT),
        ],
    )
    print(f"Created Weaviate collection: {COLLECTION_NAME}")


def already_ingested(collection, pdf_file: str, page: int) -> bool:
    result = collection.query.fetch_objects(
        filters=(
            Filter.by_property("pdf_file").equal(pdf_file)
            & Filter.by_property("page").equal(page)
        ),
        limit=1,
    )
    return len(result.objects) > 0


def delete_page(collection, pdf_file: str, page: int):
    """Delete all chunks for a given pdf_file + page (used when OVERWRITE=True)."""
    collection.data.delete_many(
        where=(
            Filter.by_property("pdf_file").equal(pdf_file)
            & Filter.by_property("page").equal(page)
        )
    )


def wv_insert(collection, objects: list[dict]):
    with collection.batch.fixed_size(batch_size=25) as batch:
        for obj in objects:
            batch.add_object(properties=obj["properties"], vector=obj["vector"])
    if collection.batch.failed_objects:
        raise RuntimeError(f"{len(collection.batch.failed_objects)} object(s) failed to insert")


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def chunk_text(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= MAX_CHUNK_CHARS:
        return [text]

    paragraphs = [p.strip() for p in re.split(r'\n\n+', text) if p.strip()]
    if not paragraphs:
        return [text]

    chunks = []
    i = 0
    while i < len(paragraphs):
        current, current_len, j = [], 0, i
        while j < len(paragraphs):
            p = paragraphs[j]
            if current_len + len(p) > MAX_CHUNK_CHARS and current:
                break
            current.append(p)
            current_len += len(p)
            j += 1
        if not current:
            # Single paragraph exceeds limit — keep it whole
            current = [paragraphs[i]]
            j = i + 1
        chunks.append("\n\n".join(current))
        # Overlap: back up from j by ~CHUNK_OVERLAP chars worth of paragraphs
        if CHUNK_OVERLAP > 0:
            overlap_chars, overlap_start = 0, j
            while overlap_start > i + 1:
                overlap_start -= 1
                overlap_chars += len(paragraphs[overlap_start])
                if overlap_chars >= CHUNK_OVERLAP:
                    break
            i = overlap_start
        else:
            i = j
    return chunks


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------

def load_transcriptions(pdf_file: str | None = None,
                        pages: list[int] | None = None) -> list[dict]:
    con = sqlite3.connect(DB_FILE)
    con.row_factory = sqlite3.Row
    query = "SELECT id, pdf_file, page, result FROM transcriptions WHERE result IS NOT NULL"
    params: list = []
    if pdf_file:
        query += " AND pdf_file = ?"
        params.append(pdf_file)
    if pages:
        query += f" AND page IN ({','.join('?' * len(pages))})"
        params.extend(pages)
    query += " ORDER BY pdf_file, page"
    rows = con.execute(query, params).fetchall()
    con.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Async embed + ingest
# ---------------------------------------------------------------------------

async def embed_chunk_async(gemini_client, embed_sem: asyncio.Semaphore,
                            chunk: str) -> list[float]:
    async with embed_sem:
        response = await asyncio.to_thread(
            gemini_client.models.embed_content,
            model=EMBEDDING_MODEL,
            contents=chunk,
        )
        await asyncio.sleep(SLEEP_BETWEEN_EMBEDS)
        return response.embeddings[0].values


async def process_page(
    page_sem: asyncio.Semaphore,
    embed_sem: asyncio.Semaphore,
    wv_lock: asyncio.Lock,
    collection,
    gemini_client,
    row: dict,
    idx: int,
    total: int,
    counters: dict,
):
    pdf_file = row["pdf_file"]
    page     = row["page"]
    label    = f"[{idx}/{total}] {Path(pdf_file).stem} p{page}"

    async with page_sem:
        try:
            chunks = chunk_text(row["result"] or "")
            if not chunks:
                print(f"{label} — WARN: no text, skipping")
                async with wv_lock:
                    counters["skipped"] += 1
                return

            vectors = await asyncio.gather(*[
                embed_chunk_async(gemini_client, embed_sem, chunk)
                for chunk in chunks
            ])

            objects = [
                {
                    "properties": {
                        "text":             chunk,
                        "transcription_id": row["id"],
                        "pdf_file":         pdf_file,
                        "pdf_stem":         Path(pdf_file).stem,
                        "page":             page,
                        "chunk_index":      i,
                        "total_chunks":     len(chunks),
                    },
                    "vector": vector,
                }
                for i, (chunk, vector) in enumerate(zip(chunks, vectors))
            ]

            async with wv_lock:
                if OVERWRITE:
                    await asyncio.to_thread(delete_page, collection, pdf_file, page)
                await asyncio.to_thread(wv_insert, collection, objects)
                counters["ingested"] += 1

            chunk_note = f"{len(chunks)} chunk(s)" if len(chunks) > 1 else "1 chunk"
            print(f"{label} — OK ({chunk_note})")

        except Exception as e:
            print(f"{label} — ERROR: {e}")
            async with wv_lock:
                counters["errors"] += 1


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def amain():
    gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    wv_client     = connect_weaviate()

    try:
        ensure_collection(wv_client)
        collection = wv_client.collections.get(COLLECTION_NAME)

        all_rows = load_transcriptions()

        if OVERWRITE:
            rows = all_rows
        else:
            rows = [r for r in all_rows
                    if not already_ingested(collection, r["pdf_file"], r["page"])]
            skipped_count = len(all_rows) - len(rows)
            if skipped_count:
                print(f"Skipping {skipped_count} already-ingested page(s) (OVERWRITE=False).")

        if LIMIT is not None:
            rows = rows[:LIMIT]

        total = len(rows)
        print(f"Processing {total} page(s)... "
              f"(PAGE_CONCURRENCY={PAGE_CONCURRENCY}, EMBED_CONCURRENCY={EMBED_CONCURRENCY})")

        page_sem  = asyncio.Semaphore(PAGE_CONCURRENCY)
        embed_sem = asyncio.Semaphore(EMBED_CONCURRENCY)
        wv_lock   = asyncio.Lock()
        counters  = {"ingested": 0, "skipped": 0, "errors": 0}

        await asyncio.gather(*[
            process_page(page_sem, embed_sem, wv_lock, collection, gemini_client,
                         row, i, total, counters)
            for i, row in enumerate(rows, start=1)
        ])

    finally:
        wv_client.close()

    print(f"\n--- Summary ---")
    print(f"  Ingested : {counters['ingested']}")
    print(f"  Skipped  : {counters['skipped']}")
    print(f"  Errors   : {counters['errors']}")


if __name__ == "__main__":
    asyncio.run(amain())
