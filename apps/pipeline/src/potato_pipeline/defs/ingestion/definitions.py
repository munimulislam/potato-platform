import dagster as dg

from potato_pipeline.defs.ingestion.assets import trial_raw_data
from potato_pipeline.defs.ingestion.jobs import file_ingest
from potato_pipeline.defs.ingestion.sensors import incoming_file_sensor
from potato_pipeline.defs.resources import dlt_resource


@dg.definitions
def definitions():
    return dg.Definitions(
        assets=[trial_raw_data],
        jobs=[file_ingest],
        sensors=[incoming_file_sensor],
        resources={"dlt": dlt_resource},
    )
