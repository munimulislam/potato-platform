"""
Unit tests for rank_varieties.py that do not need R.

Each test protects one rule that would silently produce a wrong or misleading
ranking if it broke. The R model itself is tested in test_fit_blup_r.py.
"""

import subprocess

import duckdb
import pytest
from pydantic import ValidationError

from potato_trial_pipeline.agent.common import ToolError, TraitDirection
from potato_trial_pipeline.agent.tools.rank_varieties import (
    FEW_TRIALS_WARNING,
    RankVarietiesQuery,
    _fit_in_r,
    _get_rankable_trait,
    _largest_connected_group,
    _load_cells,
    _rank_predictions,
    _trials_better_than_average,
    _variety_stats,
    for_llm,
    rank_varieties,
    render_table,
)

# monkeypatch must replace names where rank_varieties.py LOOKS THEM UP (inside that module),
# not in this test file. So patches use the module path as a string.
MODULE = "potato_trial_pipeline.agent.tools.rank_varieties"


# ---------------------------------------------------------------------------------------
# Fixtures: a tiny DuckDB with the tables the tool reads
# ---------------------------------------------------------------------------------------
@pytest.fixture
def db(make_db):
    path = make_db(
        dictionary=[
            ("o_a_score", "float", "High", True),
            ("ffdefects", "float", "Low", True),
            ("no_dir", "float", "Neutral", True),
            ("ffrots", "float", "High", False),
            ("skincolour", "str", "Neutral", True),
        ],
        experiments=[
            ("cara", "oak park 2015", "o_a_score", 2015, "ne", "oak park", 7.0),
            ("cara", "seville 2016", "o_a_score", 2016, "med", "seville", 6.0),
            ("orla", "oak park 2015", "o_a_score", 2015, "ne", "oak park", 5.0),
            ("orla", "oak park 2019", "o_a_score", 2019, "ne", "oak park", None),
            ("orla", "oak park 2015", "ffdefects", 2015, "ne", "oak park", 8.0),
        ],
    )
    con = duckdb.connect(str(path), read_only=True)
    yield con
    con.close()


def query(**kw) -> RankVarietiesQuery:
    return RankVarietiesQuery(**{"trait": "o_a_score", **kw})


# ---------------------------------------------------------------------------------------
# Query validation: what the LLM sends must be normalised or rejected, never guessed
# ---------------------------------------------------------------------------------------
def test_query_normalises_case_and_spaces():
    q = RankVarietiesQuery(trait="  O_A_Score ", locations=[" Oak Park "])
    assert q.trait == "o_a_score"
    assert q.locations == ["oak park"]


def test_query_rejects_unknown_fields():
    # A misspelt argument from the LLM must fail loudly, not be ignored silently.
    with pytest.raises(ValidationError):
        RankVarietiesQuery(trait="o_a_score", year_from=2015)


@pytest.mark.parametrize(
    "bad", [{"top_n": 0}, {"top_n": 101}, {"min_trials": 0}, {"env_type": "uk"}]
)
def test_query_rejects_out_of_range_values(bad):
    with pytest.raises(ValidationError):
        query(**bad)


# ---------------------------------------------------------------------------------------
# Trait check: a wrong direction silently inverts every ranking
# ---------------------------------------------------------------------------------------
def test_direction_high_and_low(db):
    assert _get_rankable_trait(db, "o_a_score").direction is TraitDirection.High
    assert _get_rankable_trait(db, "ffdefects").direction is TraitDirection.Low


def test_unknown_trait_error_lists_valid_traits(db):
    with pytest.raises(ToolError) as err:
        _get_rankable_trait(db, "scab")
    message = str(err.value)
    assert (
        "o_a_score" in message and "ffdefects" in message
    )  # the LLM can retry from this
    assert "ffrots" not in message  # disabled traits are never offered
    assert "skincolour" not in message  # text traits cannot be ranked
    assert "no_dir" not in message  # neutral traits cannot be ranked


@pytest.mark.parametrize("trait", ["ffrots", "skincolour", "no_dir"])
def test_non_rankable_traits_are_refused_not_guessed(db, trait):
    with pytest.raises(ToolError, match="non-rankable"):
        _get_rankable_trait(db, trait)


# ---------------------------------------------------------------------------------------
# Data loading: filters must return exactly the requested scope
# ---------------------------------------------------------------------------------------
def test_load_filters_trait_and_drops_nulls(db):
    cells = _load_cells(db, query())
    assert sorted(cells) == [
        ("cara", "oak park 2015", 7.0, 2015),
        ("cara", "seville 2016", 6.0, 2016),
        ("orla", "oak park 2015", 5.0, 2015),
    ]  # no ffdefects row, no NULL value


def test_load_filters_env_type_location_and_years(db):
    assert {c[1] for c in _load_cells(db, query(env_type="med"))} == {"seville 2016"}
    assert {c[1] for c in _load_cells(db, query(locations=["Oak Park"]))} == {
        "oak park 2015"
    }
    assert {c[1] for c in _load_cells(db, query(year_min=2016))} == {"seville 2016"}
    assert {c[1] for c in _load_cells(db, query(year_max=2015))} == {"oak park 2015"}


def test_location_text_is_a_value_not_sql(db):
    # Parameters are bound, so text that looks like SQL must simply match nothing.
    assert _load_cells(db, query(locations=["x' OR '1'='1"])) == []


# ---------------------------------------------------------------------------------------
# Connectivity: trials with no shared variety cannot be compared and must be left out
# ---------------------------------------------------------------------------------------
def test_disconnected_trials_are_excluded_and_named():
    cells = [
        ("a", "t1", 1.0, 2020),
        ("a", "t2", 1.0, 2020),
        ("b", "t2", 1.0, 2020),
        ("b", "t3", 1.0, 2020),
        ("z", "island", 1.0, 2020),
    ]
    kept, excluded = _largest_connected_group(cells)
    assert excluded == ["island"]
    assert {c[1] for c in kept} == {"t1", "t2", "t3"}


def test_one_shared_variety_links_two_groups():
    # t1 and t3 share no variety directly, but 'bridge' links them through t2.
    cells = [
        ("a", "t1", 1.0, 2020),
        ("bridge", "t1", 1.0, 2020),
        ("bridge", "t3", 1.0, 2020),
        ("c", "t3", 1.0, 2020),
    ]
    _, excluded = _largest_connected_group(cells)
    assert excluded == []


# ---------------------------------------------------------------------------------------
# Ranking: order, direction, min_trials, top_n and tie-breaks
# ---------------------------------------------------------------------------------------
def _stats(**n_trials):
    cells = [(v, f"t{i}", 1.0, 2000 + i) for v, n in n_trials.items() for i in range(n)]
    return _variety_stats(cells)


def _pred(variety, value):
    return {"variety": variety, "predicted_value": value, "se": 0.1, "reliability": 0.9}


def test_high_direction_sorts_descending():
    rows, _ = _rank_predictions(
        [_pred("a", 5), _pred("b", 7), _pred("c", 6)],
        _stats(a=3, b=3, c=3),
        TraitDirection.High,
        1,
        10,
    )
    assert [r.variety for r in rows] == ["b", "c", "a"]
    assert [r.rank for r in rows] == [1, 2, 3]


def test_low_direction_sorts_ascending():
    rows, _ = _rank_predictions(
        [_pred("a", 5), _pred("b", 7), _pred("c", 6)],
        _stats(a=3, b=3, c=3),
        TraitDirection.Low,
        1,
        10,
    )
    assert [r.variety for r in rows] == ["a", "c", "b"]


def test_min_trials_removes_thin_varieties_even_if_best():
    rows, n_candidates = _rank_predictions(
        [_pred("lucky", 9), _pred("proven", 7)],
        _stats(lucky=2, proven=20),
        TraitDirection.High,
        3,
        10,
    )
    assert [r.variety for r in rows] == ["proven"]
    assert n_candidates == 1


def test_top_n_cuts_after_filtering():
    preds = [_pred(v, s) for v, s in [("a", 9), ("b", 8), ("c", 7), ("d", 6)]]
    rows, n_candidates = _rank_predictions(
        preds, _stats(a=1, b=5, c=5, d=5), TraitDirection.High, 3, 2
    )
    assert [r.variety for r in rows] == ["b", "c"]  # 'a' filtered first, then top 2
    assert n_candidates == 3


def test_ties_prefer_more_trials_then_name():
    preds = [_pred("zeta", 7), _pred("alpha", 7), _pred("many", 7)]
    rows, _ = _rank_predictions(
        preds, _stats(zeta=3, alpha=3, many=30), TraitDirection.High, 1, 10
    )
    assert [r.variety for r in rows] == ["many", "alpha", "zeta"]


def test_variety_stats_are_correct():
    stats = _variety_stats(
        [("a", "t1", 6.0, 2012), ("a", "t2", 8.0, 2019), ("b", "t1", 5.0, 2015)]
    )
    assert stats["a"].n_trials == 2 and stats["a"].raw_mean == 7.0
    assert (stats["a"].first_year, stats["a"].last_year) == (2012, 2019)


# ---------------------------------------------------------------------------------------
# rank_varieties end to end, with R replaced by a fake result
# ---------------------------------------------------------------------------------------
def _fake_fit(predictions, **model_overrides):
    model = {
        "formula": "value ~ trial + (1 | genotype)",
        "engine": "lme4",
        "sigma2_g": 1.0,
        "sigma2_e": 1.0,
        "heritability": 0.6,
        "mean_reliability": 0.6,
        "n_varieties": 12,
        "n_trials": 6,
        "n_observations": 40,
        "converged": True,
        "singular": False,
    }
    model.update(model_overrides)
    return {
        "status": "ok",
        "model": model,
        "predictions": predictions,
        "warnings": [],
        "versions": {"R": "test"},
    }


@pytest.fixture
def connected_db(make_db, monkeypatch):
    """6 connected trials, 12 varieties, plus one isolated trial."""
    rows = [
        (f"v{v}", f"t{t}", "o_a_score", 2010 + t, "ne", "x", 5.0 + v / 10)
        for v in range(12)
        for t in range(6)
        if (v + t) % 2 == 0 or v < 2
    ]
    rows.append(("lonely", "island", "o_a_score", 2020, "ne", "x", 9.9))
    path = make_db([("o_a_score", "float", "High", True)], rows)
    monkeypatch.setattr(f"{MODULE}.settings.duckdb_path", lambda: path)
    return rows


def test_r_receives_only_the_connected_cells(connected_db, monkeypatch):
    seen = {}

    def fake(cells):
        seen["trials"] = {c[1] for c in cells}
        return _fake_fit([_pred(f"v{v}", v) for v in range(12)])

    monkeypatch.setattr(f"{MODULE}._fit_in_r", fake)
    result = rank_varieties(query(min_trials=1))
    assert "island" not in seen["trials"]
    assert result.model.trials_excluded_not_connected == ["island"]
    assert result.direction is TraitDirection.High
    assert any("left out" in w for w in result.warnings)


@pytest.mark.parametrize(
    "override, expected",
    [
        ({"heritability": 0.1}, "Low heritability"),
        ({"converged": False}, "did not fully converge"),
        ({"singular": True}, "singular"),
    ],
)
def test_model_problems_become_warnings(connected_db, monkeypatch, override, expected):
    monkeypatch.setattr(
        f"{MODULE}._fit_in_r", lambda cells: _fake_fit([_pred("v0", 1)], **override)
    )
    result = rank_varieties(query(min_trials=1))
    assert any(expected in w for w in result.warnings)


def test_thin_top_varieties_are_flagged(connected_db, monkeypatch):
    monkeypatch.setattr(
        f"{MODULE}._fit_in_r",
        lambda cells: _fake_fit([_pred("v2", 9), _pred("v0", 1)]),
    )
    result = rank_varieties(query(min_trials=1))
    assert (
        result.rows[0].variety == "v2" and result.rows[0].n_trials < FEW_TRIALS_WARNING
    )
    assert any("Few trials" in w and "v2" in w for w in result.warnings)


def test_no_data_is_an_error_not_an_empty_ranking(connected_db):
    with pytest.raises(ToolError, match="No data"):
        rank_varieties(query(year_min=2099))


def test_too_little_data_is_refused(connected_db, monkeypatch):
    monkeypatch.setattr(f"{MODULE}.MIN_TRIALS_TO_FIT", 50)
    with pytest.raises(ToolError, match="Too little data"):
        rank_varieties(query())


# ---------------------------------------------------------------------------------------
# R failures must become clear errors, never partial results
# ---------------------------------------------------------------------------------------
def test_r_timeout_becomes_tool_error(monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="Rscript", timeout=1)

    monkeypatch.setattr(f"{MODULE}.subprocess.run", timeout)
    with pytest.raises(ToolError, match="longer than"):
        _fit_in_r([("a", "t1", 1.0, 2020)])


def test_r_crash_without_output_becomes_tool_error(monkeypatch):
    monkeypatch.setattr(
        f"{MODULE}.subprocess.run",
        lambda *a, **k: subprocess.CompletedProcess(
            a, 1, "", "Error: package not found"
        ),
    )
    with pytest.raises(ToolError, match="package not found"):
        _fit_in_r([("a", "t1", 1.0, 2020)])


# ---------------------------------------------------------------------------------------
# Distinguishable from the top: computed in Python so the LLM never does this arithmetic
# ---------------------------------------------------------------------------------------
def _pred_se(variety, value, se):
    return {"variety": variety, "predicted_value": value, "se": se, "reliability": 0.9}


@pytest.mark.parametrize("direction", [TraitDirection.High, TraitDirection.Low])
def test_distinguishable_from_top(direction):
    # se_gap = sqrt(0.1^2 + 0.1^2) = 0.141 -> threshold 0.283
    sign = 1 if direction is TraitDirection.High else -1
    preds = [
        _pred_se("top", 7.0 * sign, 0.1),
        _pred_se("close", (7.0 - 0.2) * sign, 0.1),  # gap 0.2 < 0.283
        _pred_se("far", (7.0 - 0.4) * sign, 0.1),  # gap 0.4 > 0.283
    ]
    rows, _ = _rank_predictions(preds, _stats(top=3, close=3, far=3), direction, 1, 10)
    flags = {r.variety: r.distinguishable_from_top for r in rows}
    assert rows[0].variety == "top"
    assert flags == {"top": False, "close": False, "far": True}


def test_large_se_makes_a_big_gap_not_distinguishable():
    # gap 0.4 but se_gap = sqrt(0.1^2 + 0.3^2) = 0.316 -> threshold 0.632
    preds = [_pred_se("top", 7.0, 0.1), _pred_se("thin", 6.6, 0.3)]
    rows, _ = _rank_predictions(
        preds, _stats(top=3, thin=3), TraitDirection.High, 1, 10
    )
    assert rows[1].distinguishable_from_top is False


def test_for_llm_keeps_only_what_an_answer_needs(connected_db, monkeypatch):
    monkeypatch.setattr(
        f"{MODULE}._fit_in_r",
        lambda cells: _fake_fit(
            [
                _pred_se("v1", 7.0, 0.1),
                _pred_se("v2", 6.9, 0.1),
                _pred_se("v3", 6.0, 0.1),
            ]
        ),
    )
    result = rank_varieties(query(min_trials=1, env_type="ne"))
    view = for_llm(result)

    assert view["trait"] == "o_a_score" and view["better"] == "higher"
    assert view["scope"] == {"env_type": "ne"}  # only the filters that were used
    assert [r["variety"] for r in view["top"]] == ["v1", "v2", "v3"]
    assert [r["level_with_top"] for r in view["top"]] == [True, True, False]
    assert view["top"][0]["years"] == "2010-2015"
    assert view["top"][0]["beat_trial_average"].endswith(
        f"of {view['top'][0]['trials']}"
    )
    assert view["data_used"]["trials"] == 6 and 0 <= view["heritability"] <= 1
    assert "raw_mean" not in view["top"][0]  # a second number the model could misreport
    assert "versions" not in view and "query" not in view


@pytest.mark.parametrize(
    "direction, expected",
    [
        (TraitDirection.High, {"good": 2, "poor": 0}),
        (TraitDirection.Low, {"good": 0, "poor": 2}),
    ],
)
def test_trials_better_than_average(direction, expected):
    # t1 average 6, t2 average 5: good is above both, poor below both, mid equals t1's average
    cells = [
        ("good", "t1", 8.0, 2020),
        ("mid", "t1", 6.0, 2020),
        ("poor", "t1", 4.0, 2020),
        ("good", "t2", 6.0, 2021),
        ("poor", "t2", 4.0, 2021),
    ]
    better = _trials_better_than_average(cells, direction)
    assert {v: better.get(v, 0) for v in ("good", "poor")} == expected
    assert better.get("mid", 0) == 0  # equal to the average is not better


def test_table_shows_every_row_with_exact_numbers(connected_db, monkeypatch):
    monkeypatch.setattr(
        f"{MODULE}._fit_in_r",
        lambda cells: _fake_fit(
            [
                _pred_se("v1", 7.0, 0.1),
                _pred_se("v2", 6.9, 0.1),
                _pred_se("v3", 6.0, 0.1),
            ]
        ),
    )
    result = rank_varieties(query(min_trials=1, env_type="ne"))
    table = render_table(result)
    lines = table.splitlines()

    assert lines[0] == "Ranking: o_a_score (higher is better), env_type=ne"
    assert "7.00 ± 0.10" in table and "6.00 ± 0.10" in table
    row_v3 = next(line for line in lines if line.startswith("3 "))
    assert "v3" in row_v3 and row_v3.endswith("no")  # v3 is clearly below the top
    row_v1 = next(line for line in lines if line.startswith("1 "))
    assert row_v1.endswith("yes")
    assert "How to read this table" in table
