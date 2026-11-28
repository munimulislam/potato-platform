from dataclasses import dataclass
from pathlib import Path

DEFAULT_SCHEMAS = frozenset({"intermediate", "marts", "reference"})


@dataclass(frozen=True)
class AgentConfig:
    model: str
    api_key: str
    base_url: str | None = None
    temperature: float | None = 0.0
    timeout_seconds: float = 600
    max_retries: int = 0
    no_think: bool = False

    max_rounds: int = 6
    run_log_path: Path | None = None

    allowed_schemas: frozenset[str] = DEFAULT_SCHEMAS
    max_rows: int = 50

    rscript_path: Path = Path("Rscript")
