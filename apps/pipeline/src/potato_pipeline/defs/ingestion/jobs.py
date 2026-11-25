import dagster as dg

from potato_pipeline.defs.ingestion.assets import trial_raw_data

file_ingest = dg.define_asset_job(
    name="trial_ingest",
    description="Raw Excel file ingestion to DB",
    selection=[trial_raw_data],
    tags={"postgres": "trial"},
    executor_def=dg.in_process_executor,
)
