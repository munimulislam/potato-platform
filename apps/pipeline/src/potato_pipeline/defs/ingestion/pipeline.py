import os
from pathlib import Path

import dlt
import pandas as pd
from potato_core.naming import clean_column_name
from pydantic import ValidationError

from potato_pipeline.defs.ingestion.constants import COLUMNS
from potato_pipeline.defs.ingestion.models import RejectedTrialExcelRow, TrialExcelRow


def _format_errors(exc: ValidationError) -> str:
    return " | ".join(
        f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}, ({err.get('input')!r})"
        for err in exc.errors()
    )


@dlt.resource(name="excel_data", write_disposition="skip")
def load_data(file_path: str, sheet_name=0):
    file = Path(file_path)
    df = pd.read_excel(file, sheet_name=sheet_name)
    columns = [col for col in COLUMNS if col in df.columns]
    df = df[columns]
    data = df.to_dict(orient="records")

    for idx, row in enumerate(data, start=2):
        row = {clean_column_name(k): v for k, v in row.items()}
        row["source_file"] = file.name
        row["source_row"] = idx

        try:
            trial = TrialExcelRow(**row).model_dump()
            yield {"ok": True, "data": trial}
        except ValidationError as err:
            row["error_message"] = _format_errors(err)
            yield {"ok": False, "data": row}


@dlt.transformer(
    name="valids",
    write_disposition="merge",
    primary_key=["year", "location", "experiment_name", "name1", "plot"],
    schema_contract={"tables": "evolve", "columns": "freeze", "data_type": "freeze"},
    columns=TrialExcelRow,
)
def ingest_valid_rows(item: dict):
    if item["ok"]:
        yield item["data"]


@dlt.transformer(
    name="rejects",
    write_disposition="merge",
    primary_key=["source_file", "source_row"],
    columns=RejectedTrialExcelRow,
)
def ingest_quarantine_rows(item):
    if not item["ok"]:
        yield item["data"]


@dlt.source(name="potato_trial")
def trial_data_source(file_path: str):
    data_source = load_data(file_path)
    return [data_source | ingest_valid_rows, data_source | ingest_quarantine_rows]


def trial_data_pipeline():
    return dlt.pipeline(
        pipeline_name="dlt_trial_ingestion",
        destination=dlt.destinations.postgres(
            credentials={
                "host": os.environ["DB_HOST"],
                "port": int(os.environ["DB_PORT"]),
                "database": os.environ["DB_NAME"],
                "username": os.environ["DLT_USER"],
                "password": os.environ["DLT_PASSWORD"],
            }
        ),
        dataset_name="raw",
        pipelines_dir=os.environ["DLT_HOME"],
    )
