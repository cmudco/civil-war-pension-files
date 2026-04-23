# Entity Resolution & Narrative Pipeline

## Vision
The ultimate goal of this pipeline is to transform thousands of pages of unstructured, messy historical OCR text from United States Colored Troops (USCT) pension files into structured, chronological, human-readable narratives.

Historical documents are notoriously complex. A single individual may have their name spelled five different ways, enlistment dates may conflict, and locations are often misspelled or historically obsolete. This repository houses the data engineering architecture required to solve these challenges through a hybrid approach of Deterministic Grouping, Bayesian Probabilistic Matching (Splink/DuckDB), and Semantic AI Extraction (Gemini RAG).

By linking isolated entities—Names, Dates, and Locations—across tens of thousands of pages, we transition from raw text to a structured relational database, culminating in the generation of cohesive biographical stories.

## Core Research Questions Answered
This pipeline is specifically engineered to answer four critical questions:

### 1. Which person records within a single file refer to the same individual? (Local Grouping)
Before looking across the entire archive, we must resolve identities locally. The pipeline aggressively standardizes names, squashes perfect matches using Pandas, and aggregates all fragmented sentences surrounding that name into a single "context string." A custom heuristic then scans this text for keywords (e.g., "soldier," "widow," "orphan") to categorize the entity's role.

### 2. Which person records across different files refer to the same individual? (Global Grouping)
This is the hardest challenge. Two files might mention a "Jacob Jones," but are they the same person? The pipeline uses a strict Same-File Firewall (mathematically vetoing merges within the same PDF) and relies on AI-Enriched Biographical Fingerprints (comparing LLM-extracted birth years, slaveholder names, and family members) to calculate the posterior probability of a global match.

### 3. Can you identify recurring secondary figures (agents, clerks, doctors)?
Yes. Because the global linkage engine runs on all extracted names—not just primary soldiers—it inherently clusters secondary figures. A doctor who performed medical examinations for 50 different soldiers will surface in the final `GLOBAL_MASTER_EXTRACTED.csv` with a `Linked_Files_Count` of 50. Sorting by this column immediately reveals the systemic actors within the pension bureaucracy.

### 4. What approach works best for this problem at scale?
A Hybrid Cascade. No single approach works for historical data.

*   **Rule-Based (Pandas):** Best for the initial pass. Extremely fast for squashing 100% exact matches and shrinking the dataset by 50% instantly.
*   **Fuzzy/Probabilistic (Splink):** Best for structural typos and spelling variations (e.g., "Beaufort" vs "Beaufort County").
*   **LLM/Embeddings (Gemini 2.5 Flash + Weaviate):** Best for semantic extraction. Traditional algorithms cannot parse a 3-page historical narrative. We use RAG to retrieve relevant chunks and strict, zero-temperature prompting to extract structured JSON (birth, marriage, slaveholder) to fuel the final probabilistic linkage.

## Architecture & Domain Structure

### Data Storage Structure
```text
transcription/
├── dates/   
│   ├── 01_grouping_local.py
│   ├── dates_utils.py
│   └── test_local.py
├── locations/ 
│   ├── 01_grouping_local.py
│   ├── locations_utils.py
│   └── test_local.py
├── names/
│   ├── 01_grouping_local.py
│   ├── 02_extraction.py
│   ├── 03_grouping_global.py
│   ├── names_utils.py
│   ├── test_local.py
│   └── test_global.py
├── output/
└── utils/
    ├── clean_utils.py
    └── db_utils.py
```

The data engineering pipeline is organized into distinct domain packages to isolate matching logic, making the pipeline highly maintainable and verifiable.

*   **`names/`**: Scripts for matching and clustering human names. Features contextual NLP role-tagging (Primary vs Dependent) and aggressive Jaro-Winkler typological matching.
*   **`locations/`**: Scripts for deduplicating geographical places. Features historical abbreviation expansion, rigorous geo-suffix stripping (e.g., removing "county" or "city"), and multi-token overlap algorithms.
*   **`dates/`**: Scripts for collapsing historical dates. Features strict contradiction vetoes and segregates incomplete/partial dates to prevent erroneous groupings.
*   **`utils/`**: Shared, generic utilities for database interactions (`db_utils.py`) and string cleaning/merging (`clean_utils.py`).
*   **`output/`**: The destination folder where all final CSV master lists and HTML data visualizations are exported.