import duckdb
from pydantic import BaseModel, ConfigDict

from potato_trial_pipeline.agent import settings
from potato_trial_pipeline.agent.catalog import Trait, get_traits, is_rankable
from potato_trial_pipeline.agent.common import ENV_LABELS, EnvType, ToolError

SOURCE_TABLE = "main.int_trait_experiment_level"


class DescribeDataQuery(BaseModel):
    model_config = ConfigDict(extra="ignore")


class TraitCoverage(BaseModel):
    n_trials: int = 0
    n_varieties: int = 0
    first_year: int | None = None
    last_year: int | None = None
    env_types: list[EnvType] = []


class TraitInfo(Trait, TraitCoverage):
    pass


class Location(BaseModel):
    location: str
    env_type: EnvType | None
    n_trials: int
    first_year: int
    last_year: int


class Region(BaseModel):
    code: EnvType
    label: str


class DataDescription(BaseModel):
    traits: list[TraitInfo]
    locations: list[Location]
    env_types: list[Region]
    year_min: int
    year_max: int


def get_trait_coverage(conn: duckdb.DuckDBPyConnection) -> dict[str, TraitCoverage]:
    stmt = f"""
        SELECT
            trait,
            COUNT(DISTINCT experiment_name) AS n_trials,
            COUNT(DISTINCT variety) AS n_varieties,
            MIN(year) AS first_year,
            MAX(year) AS last_year,
            LIST(DISTINCT env_type ORDER BY env_type)
                FILTER (WHERE env_type IS NOT NULL) AS env_types
        FROM {SOURCE_TABLE}
        WHERE value IS NOT NULL
        GROUP BY trait
    """

    cursor = conn.cursor()
    cursor.execute(stmt)

    columns = [col[0] for col in cursor.description]
    rows = cursor.fetchall()
    coverage = {}
    for r in rows:
        row = dict(zip(columns, r))
        trait = row.pop("trait")
        coverage[trait] = TraitCoverage.model_validate(row)

    return coverage


def get_locations(conn: duckdb.DuckDBPyConnection) -> list[Location]:
    stmt = f"""
        SELECT
            location,
            env_type,
            COUNT(DISTINCT experiment_name) AS n_trials,
            MIN(year) AS first_year,
            MAX(year) AS last_year
        FROM {SOURCE_TABLE}
        WHERE value IS NOT NULL AND location IS NOT NULL
        GROUP BY location, env_type
        ORDER BY location
    """

    cursor = conn.cursor()
    cursor.execute(stmt)

    columns = [col[0] for col in cursor.description]
    rows = cursor.fetchall()
    locations = [Location.model_validate(dict(zip(columns, r))) for r in rows]

    return locations


def get_year_range(conn: duckdb.DuckDBPyConnection) -> tuple[int | None, int | None]:
    stmt = f"""
        SELECT
            MIN(year) AS year_min,
            MAX(year) AS year_max
        FROM {SOURCE_TABLE}
        WHERE value IS NOT NULL
    """

    return conn.execute(stmt).fetchone()


def describe_data(query: DescribeDataQuery) -> DataDescription:
    with duckdb.connect(str(settings.duckdb_path()), read_only=True) as conn:
        traits = [t for t in get_traits(conn) if is_rankable(t)]
        coverage = get_trait_coverage(conn)
        locations = get_locations(conn)
        year_min, year_max = get_year_range(conn)

    if not traits:
        raise ToolError("No rankable traits are enabled in trait_dictionary.")
    if year_min is None:
        raise ToolError("No trial data found.")

    return DataDescription(
        traits=[
            TraitInfo(
                **t.model_dump(),
                **coverage.get(t.trait, TraitCoverage()).model_dump(),
            )
            for t in traits
        ],
        locations=locations,
        env_types=[
            Region(code=code, label=label) for code, label in ENV_LABELS.items()
        ],
        year_min=year_min,
        year_max=year_max,
    )


if __name__ == "__main__":
    print(describe_data(DescribeDataQuery()).model_dump_json(indent=2))
