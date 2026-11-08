"""
@File        - rank_varieties.py
@Description - Agent tool: rank varieties for one trait with a REML/BLUP linear mixed model.

Flow:
  1. Validate the query against trait_dictionary (only agent-enabled numeric traits).
  2. Read variety x trial means from int_trait_experiment_level (read-only), close the DB.
  3. Check there is enough data and keep the largest group of connected trials.
  4. Fit the model in R (fit_blup.R: statgenGxE, value ~ trial + (1 | genotype)).
  5. Rank by the predicted value (direction from trait_dictionary), apply min_trials / top_n,
     and return the ranking with model statistics and plain-language warnings.

Usage:
  python -m potato_trial_pipeline.agent.tools.rank_varieties --trait o_a_score --env-type ne
"""

import argparse
import csv
import json
import subprocess
import tempfile
import time
from collections import defaultdict
from enum import Enum
from pathlib import Path
from typing import Optional

import duckdb
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.potato_trial_pipeline.agent import settings

MIN_TRIALS_TO_FIT = 5  # fewer trials in scope -> no model-based ranking
MIN_VARIETIES_TO_FIT = 10  # fewer varieties in scope -> no model-based ranking
R_TIMEOUT_SECONDS = 120
LOW_HERITABILITY = 0.3  # below this, rankings are mostly noise
FEW_TRIALS_WARNING = 5  # top-ranked varieties with fewer trials get a caveat

HIGHER_IS_BETTER = "high"
LOWER_IS_BETTER = "low"


class ToolError(Exception):
    """An error the agent can show to the user or use to correct its call."""


class EnvType(str, Enum):
    NE = "ne"
    MED = "med"


class RankVarietiesQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trait: str = Field(
        min_length=1, description="Trait name from trait_dictionary, e.g. o_a_score"
    )
    env_type: Optional[EnvType] = Field(None, description="Region: ne or med")
    locations: Optional[list[str]] = Field(
        None, description="Only trials at these locations"
    )
    year_min: Optional[int] = Field(None, ge=1900, le=2100)
    year_max: Optional[int] = Field(None, ge=1900, le=2100)
    min_trials: int = Field(
        3, ge=1, description="Only rank varieties with at least this many trials"
    )
    top_n: int = Field(10, ge=1, le=100)

    @field_validator("trait")
    @classmethod
    def normalise_trait(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("locations")
    @classmethod
    def normalise_locations(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        return [v.strip().lower() for v in value] if value else None


class _VarietyStats(BaseModel):
    n_trials: int
    raw_mean: float
    first_year: int
    last_year: int


class VarietyRank(BaseModel):
    rank: int
    variety: str
    predicted_value: float
    se: float
    reliability: float
    n_trials: int
    raw_mean: float
    first_year: int
    last_year: int


class ModelSummary(BaseModel):
    method: str
    formula: str
    engine: str
    sigma2_g: float
    sigma2_e: float
    heritability: float
    mean_reliability: float
    n_varieties: int
    n_trials: int
    n_observations: int
    n_trials_excluded_not_connected: int
    trials_excluded_not_connected: list[str]
    converged: bool
    singular: bool
    runtime_seconds: float
    versions: dict[str, str]


class RankVarietiesResult(BaseModel):
    query: RankVarietiesQuery
    direction: str
    n_varieties_ranked: int
    rows: list[VarietyRank]
    model: ModelSummary
    warnings: list[str]


Cell = tuple[str, str, float, int]  # (variety, experiment_name, value, year)


def _trait_direction(con: duckdb.DuckDBPyConnection, trait: str) -> str:
    rows = con.execute(f"""
        SELECT LOWER(TRIM(trait)), LOWER(TRIM(COALESCE(direction, '')))
        FROM main.trait_dictionary
        WHERE agent_enabled = TRUE AND LOWER(TRIM(data_type)) = 'float'
        """).fetchall()

    directions = dict(rows)

    if trait not in directions:
        valid = ", ".join(sorted(directions))
        raise ToolError(f"Unknown or disabled trait '{trait}'. Valid traits: {valid}")

    direction = directions[trait]

    if direction == HIGHER_IS_BETTER:
        return "higher_is_better"
    if direction == LOWER_IS_BETTER:
        return "lower_is_better"

    raise ToolError(
        f"Trait '{trait}' has no ranking direction in trait_dictionary ('{direction}')."
    )


def _load_cells(con: duckdb.DuckDBPyConnection, q: RankVarietiesQuery) -> list[Cell]:
    sql = f"""
            SELECT 
                variety, 
                experiment_name, 
                value, 
                year 
            FROM main.int_trait_experiment_level 
            WHERE trait = ?"""

    params: list = [q.trait]

    if q.env_type is not None:
        sql += "AND env_type = ?"
        params.append(q.env_type.value)

    if q.locations:
        sql += f"AND location IN ({', '.join('?' for _ in q.locations)})"
        params.extend(q.locations)

    if q.year_min is not None:
        sql += "AND year >= ?"
        params.append(q.year_min)

    if q.year_max is not None:
        sql += "AND year <= ?"
        params.append(q.year_max)

    sql += f"AND value IS NOT NULL"
    return con.execute(sql, params).fetchall()


def _largest_connected_group(cells: list[Cell]) -> tuple[list[Cell], list[str]]:
    """Keep the largest group of trials linked through shared varieties (union-find)."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    trials_by_variety: dict[str, set[str]] = defaultdict(set)

    for variety, trial, *_ in cells:
        trials_by_variety[variety].add(trial)
        find(trial)

    for trials in trials_by_variety.values():
        first, *rest = sorted(trials)
        for other in rest:
            parent[find(other)] = find(first)

    groups: dict[str, set[str]] = defaultdict(set)

    for trial in parent:
        groups[find(trial)].add(trial)

    largest = max(groups.values(), key=lambda g: (len(g), sorted(g)))
    kept = [c for c in cells if c[1] in largest]
    excluded = sorted(set(parent) - largest)
    return kept, excluded


def _fit_in_r(cells: list[Cell]) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        in_csv, out_json = Path(tmp) / "cells.csv", Path(tmp) / "result.json"

        with in_csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["variety", "experiment_name", "value"])
            writer.writerows(
                (variety, trial, value) for variety, trial, value, _ in cells
            )

        try:
            proc = subprocess.run(
                [
                    str(settings.rscript_path()),
                    str(settings.FIT_BLUP_SCRIPT),
                    str(in_csv),
                    str(out_json),
                ],
                capture_output=True,
                text=True,
                timeout=R_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            raise ToolError(
                f"Model fitting took longer than {R_TIMEOUT_SECONDS} s and was stopped."
            ) from None

        if not out_json.exists():
            raise ToolError(
                f"R produced no result (exit {proc.returncode}): {proc.stderr.strip()[-500:]}"
            )

        result = json.loads(out_json.read_text(encoding="utf-8"))

    if result.get("status") != "ok":
        raise ToolError(
            f"Model fitting failed: {result.get('message', 'unknown error')}"
        )

    return result


def _variety_stats(cells: list[Cell]) -> dict[str, _VarietyStats]:
    values: dict[str, list[float]] = defaultdict(list)
    years: dict[str, list[int]] = defaultdict(list)

    for variety, _, value, year in cells:
        values[variety].append(value)
        years[variety].append(year)

    return {
        v: _VarietyStats(
            n_trials=len(values[v]),
            raw_mean=sum(values[v]) / len(values[v]),
            first_year=min(years[v]),
            last_year=max(years[v]),
        )
        for v in values
    }


def _rank_predictions(
    predictions: list[dict],
    stats: dict[str, _VarietyStats],
    direction: str,
    min_trials: int,
    top_n: int,
) -> tuple[list[VarietyRank], int]:
    """Filter by min_trials, sort by predicted value in the trait's direction, keep top_n.
    Ties: more trials first, then variety name, so the order is always the same."""
    candidates = [p for p in predictions if stats[p["variety"]].n_trials >= min_trials]
    sign = -1 if direction == "higher_is_better" else 1

    candidates.sort(
        key=lambda p: (
            sign * p["predicted_value"],
            -stats[p["variety"]].n_trials,
            p["variety"],
        )
    )

    rows = [
        VarietyRank(
            rank=i,
            variety=p["variety"],
            predicted_value=p["predicted_value"],
            se=p["se"],
            reliability=p["reliability"],
            **stats[p["variety"]].model_dump(),
        )
        for i, p in enumerate(candidates[:top_n], start=1)
    ]

    return rows, len(candidates)


def _build_warnings(
    model: dict,
    r_warnings: list[str],
    excluded: list[str],
    rows: list[VarietyRank],
    n_candidates: int,
    query: RankVarietiesQuery,
) -> list[str]:

    warnings = list(r_warnings)

    if excluded:
        warnings.append(
            f"{len(excluded)} trial(s) were left out: they share no varieties with the main group."
        )

    if not model["converged"]:
        warnings.append(
            "The model did not fully converge; treat the ranking with caution."
        )

    if model["singular"]:
        warnings.append(
            "The model is singular (no detectable variety differences); the ranking is not meaningful."
        )

    if model["heritability"] < LOW_HERITABILITY:
        warnings.append(
            f"Low heritability ({model['heritability']:.2f}): rankings are mostly noise in this scope."
        )

    thin = [r.variety for r in rows if r.n_trials < FEW_TRIALS_WARNING]

    if thin:
        warnings.append(
            f"Few trials (<{FEW_TRIALS_WARNING}) for: {', '.join(thin)}. Their positions are provisional."
        )

    if n_candidates < query.top_n:
        warnings.append(
            f"Only {n_candidates} varieties have at least {query.min_trials} trials in this scope."
        )

    return warnings


def rank_varieties(query: RankVarietiesQuery) -> RankVarietiesResult:
    with duckdb.connect(str(settings.duckdb_path()), read_only=True) as con:
        direction = _trait_direction(con, query.trait)
        cells = _load_cells(con, query)

    if not cells:
        raise ToolError(
            "No data for this trait and scope. Try a wider scope (region, years, locations)."
        )

    cells, excluded = _largest_connected_group(cells)
    n_trials = len({c[1] for c in cells})
    n_varieties = len({c[0] for c in cells})

    if n_trials < MIN_TRIALS_TO_FIT or n_varieties < MIN_VARIETIES_TO_FIT:
        raise ToolError(
            f"Too little data for a model-based ranking: {n_trials} trials and {n_varieties} varieties "
            f"(need at least {MIN_TRIALS_TO_FIT} trials and {MIN_VARIETIES_TO_FIT} varieties)."
        )

    started = time.perf_counter()
    fit = _fit_in_r(cells)
    runtime = time.perf_counter() - started

    stats = _variety_stats(cells)
    rows, n_candidates = _rank_predictions(
        fit["predictions"], stats, direction, query.min_trials, query.top_n
    )
    m = fit["model"]

    return RankVarietiesResult(
        query=query,
        direction=direction,
        n_varieties_ranked=n_candidates,
        rows=rows,
        model=ModelSummary(
            method="REML/BLUP linear mixed model (statgenGxE::gxeVarComp)",
            formula=m["formula"],
            engine=m["engine"],
            sigma2_g=m["sigma2_g"],
            sigma2_e=m["sigma2_e"],
            heritability=m["heritability"],
            mean_reliability=m["mean_reliability"],
            n_varieties=m["n_varieties"],
            n_trials=m["n_trials"],
            n_observations=m["n_observations"],
            n_trials_excluded_not_connected=len(excluded),
            trials_excluded_not_connected=excluded,
            converged=m["converged"],
            singular=m["singular"],
            runtime_seconds=round(runtime, 2),
            versions=fit["versions"],
        ),
        warnings=_build_warnings(
            m, fit.get("warnings", []), excluded, rows, n_candidates, query
        ),
    )


def _main() -> None:
    parser = argparse.ArgumentParser(
        description="Rank varieties with a REML/BLUP mixed model."
    )
    parser.add_argument("--trait", required=True)
    parser.add_argument("--env-type", choices=[e.value for e in EnvType])
    parser.add_argument("--locations", nargs="*")
    parser.add_argument("--year-min", type=int)
    parser.add_argument("--year-max", type=int)
    parser.add_argument("--min-trials", type=int, default=3)
    parser.add_argument("--top-n", type=int, default=10)
    a = parser.parse_args()

    query = RankVarietiesQuery(
        trait=a.trait,
        env_type=a.env_type,
        locations=a.locations,
        year_min=a.year_min,
        year_max=a.year_max,
        min_trials=a.min_trials,
        top_n=a.top_n,
    )

    try:
        print(rank_varieties(query).model_dump_json(indent=2))
    except ToolError as e:
        print(json.dumps({"error": str(e)}, indent=2))


if __name__ == "__main__":
    _main()
