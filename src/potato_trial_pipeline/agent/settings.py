"""
@File        - settings.py
@Description - Paths and constants for the agent tools.
"""

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


def find_project_root(start: Path = Path(__file__).resolve()) -> Path:
    """Walk up from this file until the folder containing pyproject.toml."""
    for folder in [start, *start.parents]:
        if (folder / "pyproject.toml").is_file():
            return folder
    raise FileNotFoundError(f"No pyproject.toml found above {start}")


FIT_BLUP_SCRIPT = Path(__file__).resolve().parent / "r" / "fit_blup.R"
PROJECT_ROOT = find_project_root()
load_dotenv(PROJECT_ROOT / ".env", override=False)


def _required_env(name: str) -> str:
    try:
        return os.environ[name]
    except KeyError:
        raise RuntimeError(
            f"{name} is not set. Add it to .env at the project root."
        ) from None


@lru_cache
def duckdb_path() -> Path:
    return Path(_required_env("DUCKDB_PATH"))


@lru_cache
def rscript_path() -> Path:
    return Path(_required_env("RSCRIPT_PATH"))


@lru_cache
def llm_model() -> str:
    return _required_env("LLM_MODEL")


@lru_cache
def llm_api_key() -> str:
    return _required_env("LLM_API_KEY")


@lru_cache
def llm_base_url() -> str | None:
    return os.getenv("LLM_BASE_URL") or None


@lru_cache
def llm_temperature() -> float | None:
    """0 by default for repeatable answers. Set LLM_TEMPERATURE= (empty) for models that
    reject the temperature parameter (some reasoning models do)."""
    value = os.getenv("LLM_TEMPERATURE", "0")
    return float(value) if value else None


@lru_cache
def llm_timeout_seconds() -> float:
    """How long one LLM request may take. Local models on a CPU need much longer than cloud."""
    return float(os.getenv("LLM_TIMEOUT_SECONDS", "120"))


@lru_cache
def llm_max_retries() -> int:
    """Retries after a timeout, rate limit or server error. Use 0 for a local model:
    retrying a request that timed out only makes you wait the same time again."""
    return int(os.getenv("LLM_MAX_RETRIES", "2"))
