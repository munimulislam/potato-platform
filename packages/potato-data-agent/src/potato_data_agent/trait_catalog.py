from psycopg import sql
from pydantic import BaseModel, ConfigDict, Field

from potato_data_agent.common import EnvType, TraitDirection
from potato_data_agent.sql import SqlRunner

TRAIT_DICTIONARY = sql.Identifier("reference", "trait_dictionary")
EXPERIMENT_LEVEL = sql.Identifier("intermediate", "int_trait_experiment_level")


class TraitDescription(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trait: str = Field(min_length=1)
    data_type: str = Field(min_length=1)
    label: str = Field(min_length=1)
    direction: TraitDirection
    trait_group: str | None = None
    scale: str | None = None
    valid_min: float | None = None
    valid_max: float | None = None
    synonyms_keywords: str | None = None
    description: str | None = None


class TraitCoverage(BaseModel):
    n_trials: int = 0
    n_varieties: int = 0
    first_year: int | None = None
    last_year: int | None = None
    env_types: list[EnvType] = []


class Location(BaseModel):
    location: str
    env_type: EnvType | None
    n_trials: int
    first_year: int
    last_year: int


_TRAITS = sql.SQL("""
    SELECT
        LOWER(TRIM(d.trait))     AS trait,
        LOWER(TRIM(d.data_type)) AS data_type,
        d.label,
        TRIM(d.direction)        AS direction,
        d.trait_group,
        d.scale,
        d.valid_min,
        d.valid_max,
        d.synonyms_keywords,
        d.description
    FROM {table} AS d
    WHERE d.agent_enabled = TRUE
    ORDER BY 1
""").format(table=TRAIT_DICTIONARY)

_COVERAGE = sql.SQL("""
    SELECT
        trait,
        COUNT(DISTINCT experiment_name) AS n_trials,
        COUNT(DISTINCT variety)         AS n_varieties,
        MIN(year)                       AS first_year,
        MAX(year)                       AS last_year,
        COALESCE(
            array_agg(DISTINCT env_type ORDER BY env_type) FILTER (WHERE env_type IS NOT NULL),
            ARRAY[]::text[]
        )                               AS env_types
    FROM {table}
    WHERE value IS NOT NULL
    GROUP BY trait
""").format(table=EXPERIMENT_LEVEL)

_LOCATIONS = sql.SQL("""
    SELECT
        location,
        env_type,
        COUNT(DISTINCT experiment_name) AS n_trials,
        MIN(year)                       AS first_year,
        MAX(year)                       AS last_year
    FROM {table}
    WHERE value IS NOT NULL AND location IS NOT NULL
    GROUP BY location, env_type
    ORDER BY location
""").format(table=EXPERIMENT_LEVEL)

_YEARS = sql.SQL("""
    SELECT MIN(year), MAX(year)
    FROM {table}
    WHERE value IS NOT NULL
""").format(table=EXPERIMENT_LEVEL)


def get_traits(sql_runner: SqlRunner) -> list[TraitDescription]:
    result = sql_runner.run_trusted(_TRAITS)
    return [
        TraitDescription.model_validate(dict(zip(result.columns, row)))
        for row in result.rows
    ]


def is_rankable(trait: TraitDescription) -> bool:
    return trait.data_type == "float" and trait.direction in (
        TraitDirection.High,
        TraitDirection.Low,
    )


def get_trait_coverage(sql_runner: SqlRunner) -> dict[str, TraitCoverage]:
    result = sql_runner.run_trusted(_COVERAGE)
    coverage = {}
    for r in result.rows:
        row = dict(zip(result.columns, r))
        trait = row.pop("trait")
        coverage[trait] = TraitCoverage.model_validate(row)
    return coverage


def get_locations(sql_runner: SqlRunner) -> list[Location]:
    result = sql_runner.run_trusted(_LOCATIONS)
    return [Location.model_validate(dict(zip(result.columns, r))) for r in result.rows]


def get_year_range(sql_runner: SqlRunner) -> tuple[int | None, int | None]:
    year_min, year_max = sql_runner.run_trusted(_YEARS).rows[0]
    return year_min, year_max
