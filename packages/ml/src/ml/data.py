"""
@File - data.py
@Author - MdMunimul.Islam@teagasc.ie
@Created - 22/07/2026
"""

import os
from pathlib import Path

import duckdb
import pandas as pd
from dotenv import find_dotenv, load_dotenv


def _duckdb_path() -> Path:
    env_file = find_dotenv(usecwd=True)
    load_dotenv(env_file, override=False)
    value = "data/potato_breeding.duckdb"

    if not value:
        raise RuntimeError("DUCKDB_PATH is not set. Add it to the project's .env file.")

    path = Path(value).expanduser()

    if not path.is_absolute() and env_file:
        path = Path(env_file).parent / path

    return path.resolve()


def load_data() -> pd.DataFrame:
    db = _duckdb_path()

    if not db.exists():
        raise FileNotFoundError(
            f"DuckDB file not found: {db} (check DUCKDB_PATH in .env)"
        )

    with duckdb.connect(str(db), read_only=True) as conn:
        return conn.execute(f"SELECT * FROM main.stg_trials").df()
