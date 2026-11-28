"""
Tests for run_sql.py. The safety rules matter most: the LLM writes this SQL, so the tool
must refuse anything that is not a single read-only query, even if it looks harmless.
"""

import pytest

from potato_data_agent.common import ToolError
from potato_data_agent.tools.run_sql import RunSqlQuery, run_sql, schema_card

MODULE = "potato_data_agent.tools.run_sql"

EXPERIMENTS = [
    ("cara", "oak park 2015", "o_a_score", 2015, "ne", "oak park", 7.0),
    ("orla", "oak park 2015", "o_a_score", 2015, "ne", "oak park", 5.0),
    ("cara", "seville 2016", "o_a_score", 2016, "med", "seville", 6.0),
    ("cara", "oak park 2019", "o_a_score", 2019, "ne", "oak park", None),
]


@pytest.fixture
def db(make_db, monkeypatch):
    path = make_db(
        [("o_a_score", "float", "High", True), ("skincolour", "str", "Neutral", True)],
        EXPERIMENTS,
    )
    monkeypatch.setattr(f"{MODULE}.settings.duckdb_path", lambda: path)
    return path


def sql(text: str):
    return run_sql(RunSqlQuery(sql=text))


# ---------------------------------------------------------------------------------------
# Normal queries
# ---------------------------------------------------------------------------------------
def test_select_returns_columns_and_rows(db):
    result = sql(
        "SELECT location, COUNT(DISTINCT experiment_name) AS n_trials "
        "FROM main.int_trait_experiment_level WHERE value IS NOT NULL "
        "GROUP BY location ORDER BY location"
    )
    assert result.columns == ["location", "n_trials"]
    assert result.rows == [["oak park", 1], ["seville", 1]]
    assert (result.n_rows, result.truncated) == (2, False)


def test_with_query_is_allowed(db):
    result = sql("WITH t AS (SELECT 1 AS x) SELECT x FROM t")
    assert result.rows == [[1]]


def test_rows_are_limited(db, monkeypatch):
    monkeypatch.setattr(f"{MODULE}.MAX_ROWS", 2)
    result = sql("SELECT * FROM range(10)")
    assert (result.n_rows, result.truncated) == (2, True)


# ---------------------------------------------------------------------------------------
# Safety: only one read-only SELECT, no files, no network
# ---------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "bad",
    [
        "CREATE TABLE x AS SELECT 1",
        "DELETE FROM main.trait_dictionary",
        "DROP TABLE main.trait_dictionary",
        "COPY main.trait_dictionary TO 'stolen.csv'",
        "ATTACH 'other.duckdb'",
        "INSTALL httpfs",
    ],
)
def test_anything_but_select_is_refused(db, bad):
    with pytest.raises(ToolError, match="Only SELECT"):
        sql(bad)


@pytest.mark.parametrize(
    "bad",
    [
        "SET enable_external_access = true",
        "SET threads = 1",
        "PRAGMA threads = 1",
        "PRAGMA enable_profiling",
    ],
)
def test_settings_cannot_be_changed(db, bad):
    # DuckDB versions classify some PRAGMA statements differently (some as SELECT), so the
    # statement check alone is not enough. The locked configuration must refuse them anyway.
    with pytest.raises(ToolError):
        sql(bad)


def test_more_than_one_statement_is_refused(db):
    with pytest.raises(ToolError, match="exactly one"):
        sql("SELECT 1; DROP TABLE main.trait_dictionary")


def test_select_cannot_read_files(db, tmp_path):
    secret = tmp_path / "secret.csv"
    secret.write_text("password\nhunter2\n")
    with pytest.raises(ToolError, match="SQL error"):
        sql(f"SELECT * FROM read_csv('{secret}')")


def test_database_is_unchanged_after_refused_queries(db):
    with pytest.raises(ToolError):
        sql("DELETE FROM main.int_trait_experiment_level")
    assert sql("SELECT COUNT(*) FROM main.int_trait_experiment_level").rows == [[4]]


# ---------------------------------------------------------------------------------------
# Errors the LLM can learn from
# ---------------------------------------------------------------------------------------
def test_syntax_error_is_reported(db):
    with pytest.raises(ToolError, match="syntax"):
        sql("SELEC location FROM main.int_trait_experiment_level")


def test_unknown_column_is_reported_with_the_reason(db):
    with pytest.raises(ToolError) as err:
        sql("SELECT site FROM main.int_trait_experiment_level")
    assert "site" in str(err.value)


def test_slow_query_is_stopped(db, monkeypatch):
    # This query takes a few seconds; the limit is set far lower, so it must be stopped.
    # (If the time limit were missing, the query would simply finish and the test would fail.)
    monkeypatch.setattr(f"{MODULE}.SQL_TIMEOUT_SECONDS", 0.3)
    with pytest.raises(ToolError, match="longer than"):
        sql(
            "SELECT COUNT(*) FROM range(400000) a, range(2000) b "
            "WHERE (a.range + b.range) % 13 = 1"
        )


# ---------------------------------------------------------------------------------------
# The schema card that goes into the system prompt
# ---------------------------------------------------------------------------------------
def test_schema_card_describes_tables_traits_locations_and_years(db):
    card = schema_card()
    assert "main.int_trait_experiment_level" in card
    assert (
        "experiment_name VARCHAR" in card and "COUNT(DISTINCT experiment_name)" in card
    )
    assert "o_a_score (O_A_SCORE, High)" in card
    assert "skincolour" not in card  # not rankable, so not offered for ranking
    assert "Locations: oak park, seville" in card
    assert "Years: 2015 to 2016" in card  # 2019 has only a NULL value
