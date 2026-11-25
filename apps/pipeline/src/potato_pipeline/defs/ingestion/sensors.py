from pathlib import Path

import dagster as dg

from potato_pipeline.defs.ingestion.config import TrialFileConfig
from potato_pipeline.defs.ingestion.constants import FILE_EXTENSIONS
from potato_pipeline.defs.ingestion.jobs import file_ingest


def _discover_files(
    incoming_dir: Path, file_extensions: list[str]
) -> list[tuple[Path, int]]:
    """Excel files in incoming, oldest first. Skips hidden files, Excel lock files (~$...)
    and files that disappear while we look (claimed by a run)."""

    extensions = {e.lower() for e in file_extensions}
    files = []

    for f in incoming_dir.iterdir():
        if f.suffix.lower() not in extensions or f.name.startswith((".", "~$")):
            continue
        try:
            if f.is_file():
                files.append((f, f.stat().st_mtime_ns))
        except FileNotFoundError:
            continue

    return sorted(files, key=lambda item: (item[1], item[0].name))


@dg.sensor(
    job=file_ingest,
    minimum_interval_seconds=30,
    default_status=dg.DefaultSensorStatus.RUNNING,
)
def incoming_file_sensor(context: dg.AssetExecutionContext):
    incoming = Path(str(dg.EnvVar("PIPELINE_DATA_DIR").get_value())) / "incoming"

    if not incoming.exists():
        yield dg.SkipReason(f"{incoming} does not exist")
        return

    files = _discover_files(incoming, FILE_EXTENSIONS)

    if not files:
        yield dg.SkipReason("No file to process")
        return

    for f, mtime_ns in files:
        yield dg.RunRequest(
            run_key=f"{f.name}:{mtime_ns}",
            run_config=dg.RunConfig(
                ops={"trial_raw_data": TrialFileConfig(file_path=str(f))}
            ),
            tags={"file": f.name, "postgres": "trial"},
        )
