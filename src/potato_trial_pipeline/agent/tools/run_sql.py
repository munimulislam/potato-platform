"""
@File        - run_sql.py
@Description - Agent tool: run one read-only SQL SELECT against the trial database.

Safety (each one is tested):
  - exactly one statement, and it must be a SELECT (checked by DuckDB's own parser)
  - read-only connection: nothing in the database can be changed
  - no file or network access: no read_csv('C:/...'), COPY TO, ATTACH, INSTALL
  - the configuration is locked, so SQL cannot switch these back on
  - a time limit, and at most MAX_ROWS rows returned

schema_card() builds the description of the tables that goes into the system prompt.
It is generated from the database every time, so it never goes out of date.
"""

import threading
from typing import Any

import duckdb
from pydantic import BaseModel, ConfigDict, Field

from potato_trial_pipeline.agent import settings
from potato_trial_pipeline.agent.catalog import get_traits, is_rankable
from potato_trial_pipeline.agent.common import ToolError

MAX_ROWS = 50
SQL_TIMEOUT_SECONDS = 30

TABLES = {
    "main.int_trait_experiment_level": (
        "one row per variety x trial x trait; value = the variety's mean over its plots "
        "in that trial"
    ),
    "main.trait_dictionary": "one row per trait: meaning, scale, direction",
}

COLUMN_NOTES = {
    "variety": "the variety, lowercase; users also say clone, cultivar, genotype, line",
    "experiment_name": (
        "the trial; users also say experiment, field trial; "
        "count trials with COUNT(DISTINCT experiment_name)"
    ),
    "trait": (
        "trait name, lowercase, e.g. o_a_score; users also say characteristic, "
        "attribute, metric, measurement"
    ),
    "year": "trial year; users also say season",
    "env_type": (
        "region; users also say environment, environment type, env group, zone; "
        "'ne' = North Europe (users may say northern, north), "
        "'med' = Mediterranean (users may say southern, south)"
    ),
    "location": "trial location, lowercase; users also say site, trial site, place, station",
    "value": (
        "the trait value (score or measurement); can be NULL, "
        "so filter with value IS NOT NULL"
    ),
    "n_plots": "number of plots behind the value",
    "direction": "High = higher is better, Low = lower is better",
    "agent_enabled": "only use traits where this is TRUE",
}

SQL_RULES = """\
SQL rules:
- DuckDB SQL. Text values are lowercase: WHERE location = 'oak park'.
- Always add value IS NOT NULL when counting or averaging values.
- Trials: COUNT(DISTINCT experiment_name). Varieties: COUNT(DISTINCT variety).
- Variety names are not always written the same way; match parts with ILIKE '%name%'.
- Return few rows: aggregate (GROUP BY) instead of listing raw rows. At most 50 rows come back.
- Never rank or compare varieties with AVG(value): averages ignore how hard each trial was.
  Use rank_varieties for any "best", "top" or "compare" question."""


class RunSqlQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sql: str = Field(min_length=1, description="One DuckDB SELECT statement")


class SqlResult(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    n_rows: int
    truncated: bool  # True if there were more than MAX_ROWS rows


def _connect() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(
        str(settings.duckdb_path()),
        read_only=True,
        config={"enable_external_access": False, "lock_configuration": True},
    )


def _check_statement(sql: str) -> None:
    try:
        statements = duckdb.extract_statements(sql)
    except duckdb.Error as e:
        raise ToolError(f"SQL syntax error: {e}") from None

    if len(statements) != 1:
        raise ToolError("Send exactly one SQL statement.")

    if statements[0].type != duckdb.StatementType.SELECT:
        raise ToolError("Only SELECT queries are allowed.")


def run_sql(query: RunSqlQuery) -> SqlResult:
    _check_statement(query.sql)

    with _connect() as conn:
        timer = threading.Timer(SQL_TIMEOUT_SECONDS, conn.interrupt)
        timer.start()

        try:
            cursor = conn.execute(query.sql)
            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchmany(MAX_ROWS + 1)
        except duckdb.InterruptException:
            raise ToolError(
                f"The query took longer than {SQL_TIMEOUT_SECONDS} s and was stopped. "
                "Make it simpler or more selective."
            ) from None
        except duckdb.Error as e:
            raise ToolError(f"SQL error: {e}") from None
        finally:
            timer.cancel()

    return SqlResult(
        columns=columns,
        rows=[list(r) for r in rows[:MAX_ROWS]],
        n_rows=min(len(rows), MAX_ROWS),
        truncated=len(rows) > MAX_ROWS,
    )


def schema_card() -> str:
    """Tables, columns, traits, regions, locations and years, for the system prompt."""
    with _connect() as conn:
        columns = conn.execute(
            """
            SELECT table_schema || '.' || table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema || '.' || table_name IN (SELECT UNNEST(?))
            ORDER BY table_name, ordinal_position
            """,
            [list(TABLES)],
        ).fetchall()

        traits = [t for t in get_traits(conn) if is_rankable(t)]

        locations = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT location FROM main.int_trait_experiment_level "
                "WHERE value IS NOT NULL AND location IS NOT NULL ORDER BY location"
            ).fetchall()
        ]

        year_min, year_max = conn.execute(
            "SELECT MIN(year), MAX(year) FROM main.int_trait_experiment_level "
            "WHERE value IS NOT NULL"
        ).fetchone()

    lines = ["# Database (for run_sql)"]

    for table, about in TABLES.items():
        lines.append(f"{table}: {about}")
        for t, column, data_type in columns:
            if t == table:
                note = COLUMN_NOTES.get(column, "")
                lines.append(f"  {column} {data_type}" + (f" - {note}" if note else ""))

    lines.append(
        "Traits that rank_varieties accepts: "
        + "; ".join(f"{t.trait} ({t.label}, {t.direction.value})" for t in traits)
    )

    lines.append("Regions (env_type): ne = North Europe, med = Mediterranean")
    lines.append("Locations: " + ", ".join(locations))
    lines.append(f"Years: {year_min} to {year_max}")
    lines.append(SQL_RULES)

    return "\n".join(lines)


if __name__ == "__main__":
    print(schema_card())
