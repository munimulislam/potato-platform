"""
Tests for describe_data.py.

The most important tests are the contract tests: every trait and location that
describe_data shows the LLM must be accepted by rank_varieties. Otherwise the agent
picks values from describe_data and then fails with "no data".
"""

import json

import duckdb
import pytest

from potato_trial_pipeline.agent.common import EnvType, ToolError, TraitDirection
from potato_trial_pipeline.agent.tools.describe_data import (
    DescribeDataQuery,
    describe_data,
)
from potato_trial_pipeline.agent.tools.rank_varieties import (
    RankVarietiesQuery,
    _get_rankable_trait,
    _load_cells,
)

MODULE = "potato_trial_pipeline.agent.tools.describe_data"

DICTIONARY = [
    ("o_a_score", "float", "High", True),
    ("ffdefects", "float", "Low", True),
    ("no_dir", "float", "Neutral", True),  # enabled but not rankable
    ("skincolour", "str", "Neutral", True),  # text trait
    ("ffrots", "float", "High", False),  # disabled
    ("drymatter", "float", "High", True),  # rankable but no data yet
]

EXPERIMENTS = [
    ("cara", "oak park 2015", "o_a_score", 2015, "ne", "oak park", 7.0),
    ("orla", "oak park 2015", "o_a_score", 2015, "ne", "oak park", 5.0),
    ("cara", "seville 2016", "o_a_score", 2016, "med", "seville", 6.0),
    ("cara", "oak park 2019", "o_a_score", 2019, "ne", "oak park", None),  # NULL value
    ("rooster", "carlow 2021", "o_a_score", 2021, "ne", "carlow", None),  # only NULLs
    ("orla", "oak park 2015", "ffdefects", 2015, "ne", "oak park", 8.0),
]

LOCATION_MAP = [
    ("oak park", "ne"),
    ("seville", "med"),
    ("valladolid", "med"),
]  # no data


@pytest.fixture
def db(make_db, monkeypatch):
    path = make_db(DICTIONARY, EXPERIMENTS, LOCATION_MAP)
    monkeypatch.setattr(f"{MODULE}.settings.duckdb_path", lambda: path)
    return path


def traits_by_name(result):
    return {t.trait: t for t in result.traits}


# ---------------------------------------------------------------------------------------
# What is listed
# ---------------------------------------------------------------------------------------
def test_only_rankable_traits_are_listed(db):
    assert set(traits_by_name(describe_data(DescribeDataQuery()))) == {
        "o_a_score",
        "ffdefects",
        "drymatter",
    }


def test_trait_coverage_is_exact_and_ignores_nulls(db):
    t = traits_by_name(describe_data(DescribeDataQuery()))["o_a_score"]
    # oak park 2019 and carlow 2021 have only NULL values, so they do not count
    assert (t.n_trials, t.n_varieties) == (2, 2)
    assert (t.first_year, t.last_year) == (2015, 2016)
    assert t.env_types == [EnvType.MED, EnvType.NE]
    assert t.direction is TraitDirection.High


def test_trait_without_data_is_listed_with_zero_coverage(db):
    t = traits_by_name(describe_data(DescribeDataQuery()))["drymatter"]
    assert (t.n_trials, t.first_year, t.env_types) == (0, None, [])


def test_locations_come_from_data_not_from_location_map(db):
    result = describe_data(DescribeDataQuery())
    assert [loc.location for loc in result.locations] == ["oak park", "seville"]
    # valladolid is only in location_map; carlow only has NULL values


def test_year_range_ignores_nulls(db):
    result = describe_data(DescribeDataQuery())
    assert (result.year_min, result.year_max) == (2015, 2016)


# ---------------------------------------------------------------------------------------
# Contract with rank_varieties
# ---------------------------------------------------------------------------------------
def test_every_listed_trait_is_accepted_by_rank_varieties(db):
    result = describe_data(DescribeDataQuery())
    with duckdb.connect(str(db), read_only=True) as conn:
        for t in result.traits:
            assert _get_rankable_trait(conn, t.trait).direction is t.direction


def test_unlisted_enabled_traits_are_refused_by_rank_varieties(db):
    with duckdb.connect(str(db), read_only=True) as conn:
        for name in ("no_dir", "skincolour", "ffrots"):
            with pytest.raises(ToolError):
                _get_rankable_trait(conn, name)


def test_every_listed_location_finds_data_in_rank_varieties(db):
    result = describe_data(DescribeDataQuery())
    with duckdb.connect(str(db), read_only=True) as conn:
        for loc in result.locations:
            cells = _load_cells(
                conn, RankVarietiesQuery(trait="o_a_score", locations=[loc.location])
            )
            assert cells, f"location '{loc.location}' finds no data in rank_varieties"


# ---------------------------------------------------------------------------------------
# Output and errors
# ---------------------------------------------------------------------------------------
def _reject_nan(token):
    raise ValueError(f"invalid JSON constant: {token}")


def test_output_is_strict_json_even_with_null_values(db):
    # valid_min is NULL for every trait in the fixture
    text = describe_data(DescribeDataQuery()).model_dump_json()
    data = json.loads(text, parse_constant=_reject_nan)
    assert data["traits"][0]["valid_min"] is None


def test_no_rankable_traits_is_an_error(make_db, monkeypatch):
    path = make_db([("skincolour", "str", "Neutral", True)], EXPERIMENTS)
    monkeypatch.setattr(f"{MODULE}.settings.duckdb_path", lambda: path)
    with pytest.raises(ToolError, match="No rankable traits"):
        describe_data(DescribeDataQuery())


def test_no_data_is_an_error(make_db, monkeypatch):
    path = make_db(DICTIONARY)
    monkeypatch.setattr(f"{MODULE}.settings.duckdb_path", lambda: path)
    with pytest.raises(ToolError, match="No trial data"):
        describe_data(DescribeDataQuery())


def test_stray_arguments_are_ignored(db):
    # Weak models send arguments to this no-argument tool (seen in a real run).
    # They must not block the call: the full description comes back as usual.
    query = DescribeDataQuery.model_validate({"trait": "mealiness", "top_n": "null"})
    assert query.model_dump() == {}
    assert describe_data(query).traits
