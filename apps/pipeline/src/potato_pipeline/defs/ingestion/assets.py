import os
import shutil
import traceback
from datetime import datetime
from pathlib import Path

import dagster as dg
from dagster_dlt import DagsterDltResource, dlt_assets

from potato_pipeline.defs.ingestion.config import TrialFileConfig
from potato_pipeline.defs.ingestion.pipeline import (
    trial_data_pipeline,
    trial_data_source,
)

DATA_DIR = Path(str(dg.EnvVar("PIPELINE_DATA_DIR").get_value()))
PROCESSING_DIR = DATA_DIR / "processing"
ARCHIVE_DIR = DATA_DIR / "archive"
FAILED_DIR = DATA_DIR / "failed"

data_pipeline = trial_data_pipeline()


def _move(file: Path, target_dir: Path) -> Path:
    """
    Move a file into target_dir. Adds a timestamp if the name is already taken.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / file.name

    if target.exists():
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target = target_dir / f"{file.stem}_{stamp}{file.suffix}"

    return Path(shutil.move(str(file), str(target)))


def _remove_empty(folder: Path) -> None:
    try:
        folder.rmdir()
    except OSError:
        pass


def claim(file: Path, run_id: str) -> Path:
    """
    Move the file from incoming into processing/<run_id>/, keeping its name.
    os.replace is atomic: if two runs try, only one gets the file.
    """
    run_dir = PROCESSING_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    claimed = run_dir / file.name

    try:
        os.replace(file, claimed)
    except FileNotFoundError as e:
        _remove_empty(run_dir)
        raise dg.Failure(
            f"{file.name} is no longer in incoming (taken by another run or removed)."
        ) from e

    return claimed


@dlt_assets(
    dlt_source=trial_data_source(file_path="__placeholder__"),
    dlt_pipeline=data_pipeline,
    group_name="trial_data_source",
)
def trial_raw_data(
    context: dg.AssetExecutionContext, dlt: DagsterDltResource, config: TrialFileConfig
):
    """
    Ingest excel data and load them into valid and reject table with dlt
    """
    claimed = claim(Path(config.file_path), context.run_id)
    context.log.info(f"Claimed {claimed.name} -> {claimed.parent}")

    try:
        data_pipeline.drop_pending_packages()
        yield from dlt.run(
            context=context, dlt_source=trial_data_source(file_path=str(claimed))
        )
    except Exception:
        failed = _move(claimed, FAILED_DIR)
        failed.with_name(failed.name + ".error.txt").write_text(traceback.format_exc())
        _remove_empty(claimed.parent)
        context.log.error(f"Moved to failed: {failed.name} (see .error.txt)")
        raise

    archived = _move(claimed, ARCHIVE_DIR)
    _remove_empty(claimed.parent)
    context.log.info(f"Archived -> {archived.name}")
