"""
The example SQL goes into every prompt, and a small model copies it closely.
So every example must be valid and must run on the real table layout.
"""

import re

import pytest

from potato_trial_pipeline.agent.loop import build_system_prompt, load_sql_examples
from potato_trial_pipeline.agent.tools.run_sql import RunSqlQuery, run_sql

SQL_BLOCK = re.compile(r"```sql\n(.*?)```", re.DOTALL)
EXAMPLES = SQL_BLOCK.findall(load_sql_examples())


@pytest.fixture
def db(make_db, monkeypatch):
    path = make_db(
        [("mealiness", "float", "High", True)],
        [("cristina", "oak park 2015", "mealiness", 2015, "ne", "oak park", 6.0)],
    )
    monkeypatch.setattr(
        "potato_trial_pipeline.agent.tools.run_sql.settings.duckdb_path", lambda: path
    )
    return path


def test_there_are_examples():
    assert len(EXAMPLES) >= 5


@pytest.mark.parametrize(
    "sql", EXAMPLES, ids=[f"example_{i}" for i in range(len(EXAMPLES))]
)
def test_every_example_runs(db, sql):
    run_sql(
        RunSqlQuery(sql=sql)
    )  # raises ToolError if invalid, not a SELECT, or wrong columns


def test_every_example_that_counts_or_averages_values_filters_nulls():
    for sql in EXAMPLES:
        if "int_trait_experiment_level" in sql:
            assert "value IS NOT NULL" in sql, sql


def test_ranking_questions_are_sent_to_rank_varieties():
    assert "rank_varieties" in load_sql_examples()


def test_examples_are_in_the_system_prompt(monkeypatch):
    monkeypatch.setattr("potato_trial_pipeline.agent.loop.schema_card", lambda: "")
    assert "Q: How many trials were at Oak Park?" in build_system_prompt()


def _example(question: str) -> str:
    text = load_sql_examples()
    start = text.index(question)
    return SQL_BLOCK.search(text, start).group(1)


@pytest.fixture
def stats_db(make_db, monkeypatch):
    # mealiness at oak park: values 6, 8 and one missing (NULL); 2 trials, 2 varieties
    path = make_db(
        [("mealiness", "float", "High", True)],
        [
            ("cara", "oak park 2015", "mealiness", 2015, "ne", "oak park", 6.0),
            ("orla", "oak park 2016", "mealiness", 2016, "ne", "oak park", 8.0),
            ("rooster", "oak park 2016", "mealiness", 2016, "ne", "oak park", None),
        ],
    )
    monkeypatch.setattr(
        "potato_trial_pipeline.agent.tools.run_sql.settings.duckdb_path", lambda: path
    )


@pytest.mark.parametrize(
    "question", ["Tell me about the mealiness trait.", "Tell me about Oak Park."]
)
def test_profile_examples_compute_the_right_numbers(stats_db, question):
    # The model copies these formulas, so the formulas themselves must be right.
    result = run_sql(RunSqlQuery(sql=_example(question)))
    row = dict(zip(result.columns, result.rows[0]))
    assert (row["n_trials"], row["n_varieties"], row["n_years"]) == (2, 2, 2)
    assert (row["first_year"], row["last_year"]) == (2015, 2016)
    assert row["n_values"] == 2
    assert row["pct_missing"] == 33.3
    assert (row["mean"], row["median"], row["min"], row["max"]) == (7.0, 7.0, 6.0, 8.0)
    assert row["p25"] == 6.5 and row["p75"] == 7.5
