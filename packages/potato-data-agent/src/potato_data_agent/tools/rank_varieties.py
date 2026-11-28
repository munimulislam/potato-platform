import csv
import json
import subprocess
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Optional

from psycopg import sql
from pydantic import BaseModel, ConfigDict, Field, field_validator

from potato_data_agent.common import EnvType, ToolError, TraitDirection
from potato_data_agent.context import ToolContext
from potato_data_agent.sql import SqlRunner
from potato_data_agent.trait_catalog import TraitDescription, get_traits, is_rankable

FIT_BLUP_SCRIPT = (
    Path(__file__).resolve().parent.parent / "r" / "fit_blup.R"
)  # shipped inside the package

MIN_TRIALS_TO_FIT = 5  # fewer trials in scope -> no model-based ranking
MIN_VARIETIES_TO_FIT = 10  # fewer varieties in scope -> no model-based ranking
R_TIMEOUT_SECONDS = 120
LOW_HERITABILITY = 0.3  # below this, rankings are mostly noise
FEW_TRIALS_WARNING = 5  # top-ranked varieties with fewer trials get a caveat

# Every variety x trial cell in scope: parameterised, and never truncated (run_trusted)
_CELLS = sql.SQL("""
    SELECT variety, experiment_name, value, year
    FROM {table}
    WHERE trait = %(trait)s
      AND value IS NOT NULL
      AND (%(env_type)s::text    IS NULL OR env_type = %(env_type)s)
      AND (%(locations)s::text[] IS NULL OR location = ANY(%(locations)s))
      AND (%(year_min)s::int     IS NULL OR year >= %(year_min)s)
      AND (%(year_max)s::int     IS NULL OR year <= %(year_max)s)
""").format(table=sql.Identifier("intermediate", "int_trait_experiment_level"))


class RankVarietiesQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trait: str = Field(
        min_length=1, description="Trait name from describe_data, e.g. o_a_score"
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
    distinguishable_from_top: bool = Field(
        description="True if clearly different from rank 1: gap > 2 x sqrt(se_top^2 + se^2). "
        "Approximate; ignores the correlation between predictions."
    )
    trials_better_than_average: int = Field(
        0,
        description="In how many of its trials it did better than that trial's average",
    )


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
    direction: TraitDirection
    n_varieties_ranked: int
    rows: list[VarietyRank]
    model: ModelSummary
    warnings: list[str]


def _get_rankable_trait(sql_runner: SqlRunner, trait: str) -> TraitDescription:
    traits = {t.trait: t for t in get_traits(sql_runner) if is_rankable(t)}
    if trait not in traits:
        valid = ", ".join(sorted(traits))
        raise ToolError(
            f"Unknown or non-rankable trait '{trait}'. Valid traits: {valid}"
        )
    return traits[trait]


Cell = tuple[str, str, float, int]


def _load_cells(sql_runner: SqlRunner, q: RankVarietiesQuery) -> list[Cell]:
    result = sql_runner.run_trusted(
        _CELLS,
        {
            "trait": q.trait,
            "env_type": q.env_type.value if q.env_type is not None else None,
            "locations": q.locations,
            "year_min": q.year_min,
            "year_max": q.year_max,
        },
    )
    return [
        (variety, trial, float(value), int(year))
        for variety, trial, value, year in result.rows
    ]


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


def _fit_in_r(cells: list[Cell], rscript_path: Path) -> dict:
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
                [str(rscript_path), str(FIT_BLUP_SCRIPT), str(in_csv), str(out_json)],
                capture_output=True,
                text=True,
                timeout=R_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            raise ToolError(
                f"Model fitting took longer than {R_TIMEOUT_SECONDS} s and was stopped."
            ) from None

        except FileNotFoundError:
            raise ToolError(
                f"R is not installed here (looked for {rscript_path}); rankings are unavailable."
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


class _VarietyStats(BaseModel):
    n_trials: int
    raw_mean: float
    first_year: int
    last_year: int


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


def _differs(p: dict, top: dict) -> bool:
    """Is the gap to the top variety bigger than about 2 standard errors of the gap?"""
    gap = abs(p["predicted_value"] - top["predicted_value"])
    se_gap = (p["se"] ** 2 + top["se"] ** 2) ** 0.5
    return p is not top and gap > 2 * se_gap


def _trials_better_than_average(
    cells: list[Cell], direction: TraitDirection
) -> dict[str, int]:
    """Per variety: in how many of its trials it beat the trial average (all varieties in
    that trial). Plain evidence a breeder can check, next to the model's prediction."""
    by_trial: dict[str, list[float]] = defaultdict(list)

    for _, trial, value, _ in cells:
        by_trial[trial].append(value)

    trial_mean = {t: sum(v) / len(v) for t, v in by_trial.items()}
    better: dict[str, int] = defaultdict(int)

    for variety, trial, value, _ in cells:
        if direction == TraitDirection.High and value > trial_mean[trial]:
            better[variety] += 1
        elif direction == TraitDirection.Low and value < trial_mean[trial]:
            better[variety] += 1

    return better


def _rank_predictions(
    predictions: list[dict],
    stats: dict[str, _VarietyStats],
    direction: TraitDirection,
    min_trials: int,
    top_n: int,
) -> tuple[list[VarietyRank], int]:
    """Filter by min_trials, sort by predicted value in the trait's direction, keep top_n.
    Ties: more trials first, then variety name, so the order is always the same."""

    candidates = [p for p in predictions if stats[p["variety"]].n_trials >= min_trials]
    sign = -1 if direction == TraitDirection.High else 1
    candidates.sort(
        key=lambda p: (
            sign * p["predicted_value"],
            -stats[p["variety"]].n_trials,
            p["variety"],
        )
    )
    top = candidates[0] if candidates else None
    rows = [
        VarietyRank(
            rank=i,
            variety=p["variety"],
            predicted_value=p["predicted_value"],
            se=p["se"],
            reliability=p["reliability"],
            distinguishable_from_top=_differs(p, top),
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


def rank_varieties(query: RankVarietiesQuery, ctx: ToolContext) -> RankVarietiesResult:
    direction = _get_rankable_trait(ctx.sql, query.trait).direction
    cells = _load_cells(ctx.sql, query)

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
    fit = _fit_in_r(cells, ctx.config.rscript_path)
    runtime = time.perf_counter() - started

    stats = _variety_stats(cells)
    rows, n_candidates = _rank_predictions(
        fit["predictions"], stats, direction, query.min_trials, query.top_n
    )
    better = _trials_better_than_average(cells, direction)
    rows = [
        r.model_copy(update={"trials_better_than_average": better.get(r.variety, 0)})
        for r in rows
    ]
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


def for_llm(result: RankVarietiesResult) -> dict:
    """The short version the LLM reads: what an answer needs, plus the evidence behind it,
    with plain field names. Fewer tokens and less to misread for a small model."""
    q, m = result.query, result.model
    scope = q.model_dump(mode="json", exclude={"trait", "min_trials", "top_n"})
    scope = {k: v for k, v in scope.items() if v is not None}
    return {
        "trait": q.trait,
        "better": "higher" if result.direction == TraitDirection.High else "lower",
        "scope": scope or "all trials",
        "method": "mixed model (REML/BLUP) that corrects for differences between trials",
        "data_used": {
            "trials": m.n_trials,
            "varieties": m.n_varieties,
            "values": m.n_observations,
            "varieties_ranked": result.n_varieties_ranked,
        },
        "heritability": m.heritability,
        "top": [
            {
                "rank": r.rank,
                "variety": r.variety,
                "value": r.predicted_value,
                "se": r.se,
                "reliability": r.reliability,
                "trials": r.n_trials,
                "beat_trial_average": f"{r.trials_better_than_average} of {r.n_trials}",
                "years": f"{r.first_year}-{r.last_year}",
                "level_with_top": not r.distinguishable_from_top,
            }
            for r in result.rows
        ],
        "warnings": result.warnings,
    }


TABLE_LEGEND = """\
How to read this table:
  Predicted     the model's estimate of the variety's average, corrected for how good or poor
                the conditions in each of its trials were; ± is the standard error (uncertainty)
  Reliability   how much evidence there is for this variety, 0 to 1 (0.8+ strong, below 0.5 weak)
  Beat average  in how many of its trials it did better than that trial's average
  Top group     yes = statistically level with rank 1, so not clearly worse than the top"""


def render_table(result: RankVarietiesResult) -> str:
    """The ranking as a plain-text table, shown to the user exactly as computed.
    The LLM never retypes these numbers, so they cannot be miscopied."""
    q, m = result.query, result.model
    better = "higher" if result.direction == TraitDirection.High else "lower"
    scope = q.model_dump(mode="json", exclude={"trait", "min_trials", "top_n"})
    scope_text = ", ".join(f"{k}={v}" for k, v in scope.items() if v is not None)

    header = ["Rank", "Variety", "Predicted", "Reliability", "Trials", "Beat average"]
    header += ["Years", "Top group"]
    rows = [
        [
            str(r.rank),
            r.variety,
            f"{r.predicted_value:.2f} ± {r.se:.2f}",
            f"{r.reliability:.2f}",
            str(r.n_trials),
            f"{r.trials_better_than_average} of {r.n_trials}",
            f"{r.first_year}-{r.last_year}",
            "no" if r.distinguishable_from_top else "yes",
        ]
        for r in result.rows
    ]
    widths = [max(len(row[i]) for row in [header, *rows]) for i in range(len(header))]

    def line(cells: list[str]) -> str:
        return "  ".join(c.ljust(w) for c, w in zip(cells, widths)).rstrip()

    return "\n".join(
        [
            f"Ranking: {q.trait} ({better} is better), {scope_text or 'all trials'}",
            f"Mixed model (REML/BLUP) on {m.n_trials} trials, {m.n_varieties} varieties, "
            f"{m.n_observations} values; heritability {m.heritability:.2f}",
            "",
            line(header),
            line(["-" * w for w in widths]),
            *[line(row) for row in rows],
            "",
            TABLE_LEGEND,
        ]
    )
