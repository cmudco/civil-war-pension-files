import os
import importlib

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT_DIR, "transcriber_db.db")
OUTPUT_DIR = os.path.join(ROOT_DIR, "grouping_scripts", "output")

names_utils = importlib.import_module('names.names_utils')
build_master_list = names_utils.build_master_list
load_persons_from_db = names_utils.load_persons_from_db
update_database_with_clusters_names = names_utils.update_database_with_clusters

locations_utils = importlib.import_module('locations.locations_utils')
load_locations_from_db = locations_utils.load_locations_from_db

dates_utils = importlib.import_module('dates.dates_utils')
load_dates_from_db = dates_utils.load_dates_from_db

db_utils = importlib.import_module('utils.db_utils')
update_cluster_ids_locs = db_utils.update_cluster_ids
update_cluster_ids_dates = db_utils.update_cluster_ids

run_local_locations_dedupe = importlib.import_module('locations.01_grouping_local').run_local_locations_dedupe
run_local_dates_dedupe = importlib.import_module('dates.01_grouping_local').run_local_dates_dedupe
run_person_dedupe = importlib.import_module('names.01_grouping_local').run_person_dedupe
run_extraction_pipeline = importlib.import_module('names.02_extraction').run_extraction_pipeline
run_splink_linkage = importlib.import_module('names.03_grouping_global').run_splink_linkage

def main():
    print("STARTING GROUPING PIPELINE")
    
    # 1. Run the local grouping (These update the SQLite DB)
    print("\n[STEP 1] Running Local Grouping...")
    
    print("\n--- Locations ---")
    df_locs = load_locations_from_db(DB_PATH)
    loc_csv = os.path.join(OUTPUT_DIR, "LOCAL_LOCATIONS_CLUSTERS.csv")
    full_clusters_df = run_local_locations_dedupe(df_locs, loc_csv)
    if full_clusters_df is not None:
        update_cluster_ids_locs(DB_PATH, "locations", "id", "cluster_id", full_clusters_df)

    print("\n--- Dates ---")
    df_dates = load_dates_from_db(DB_PATH)
    date_csv = os.path.join(OUTPUT_DIR, "LOCAL_DATES_CLUSTERS.csv")
    date_clusters_df = run_local_dates_dedupe(df_dates, date_csv)
    if date_clusters_df is not None:
        update_cluster_ids_dates(DB_PATH, "dates", "id", "cluster_id", date_clusters_df)

    print("\n--- Names ---")
    df_people = load_persons_from_db(DB_PATH)
    name_csv = os.path.join(OUTPUT_DIR, "LOCAL_FILE_CLUSTERS.csv")
    name_clusters_df = run_person_dedupe(df_people, name_csv)
    if name_clusters_df is not None:
        update_database_with_clusters_names(name_clusters_df, DB_PATH)
        
        # Build MASTER_LOCAL_NAMES.csv to match behavior of 01_grouping_local.py standalone
        master_df = build_master_list(DB_PATH)
        if not master_df.empty:
            master_csv = os.path.join(OUTPUT_DIR, "MASTER_LOCAL_NAMES.csv")
            master_df.to_csv(master_csv, index=False)
            print(f"  [DONE] Master profiles -> {master_csv}")
    
    # 2. Pass it to Extraction (Phase 2)
    # Phase 2 returns an updated master_df that includes the new Gemini extractions
    enriched_master_df = run_extraction_pipeline(master_df)
    
    # 3. Pass the enriched data straight into Global Linkage (Phase 3)
    run_splink_linkage(enriched_master_df)

    print("\n✅ FULL PIPELINE COMPLETE.")

if __name__ == "__main__":
    main()