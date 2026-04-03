import os
from dotenv import load_dotenv
import weaviate
from weaviate.auth import AuthApiKey

load_dotenv()

COLLECTION_NAME  = "CivilWarPensionPage"
WEAVIATE_HTTP_PORT = 443
WEAVIATE_GRPC_PORT = 443


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


client = connect_weaviate()

try:
    collection = client.collections.get(COLLECTION_NAME)
    result = collection.query.fetch_objects(limit=10)

    print(f"Fetched {len(result.objects)} object(s) from '{COLLECTION_NAME}'\n")
    for i, obj in enumerate(result.objects, start=1):
        p = obj.properties
        print(f"{'='*60}")
        print(f"[{i}] {p.get('pdf_stem')}  |  page {p.get('page')}  |  chunk {p.get('chunk_index')}/{p.get('total_chunks', 1) - 1}")
        print(f"{'─'*60}")
        print(p.get("text", ""))
        print()
finally:
    client.close()
