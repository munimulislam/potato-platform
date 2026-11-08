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


load_dotenv(find_project_root() / ".env", override=False)

FIT_BLUP_SCRIPT = Path(__file__).resolve().parent / "r" / "fit_blup.R"


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
