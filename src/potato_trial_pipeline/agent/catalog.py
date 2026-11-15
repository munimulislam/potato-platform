import duckdb
from pydantic import BaseModel, ConfigDict, Field

from potato_trial_pipeline.agent.common import TraitDirection


class Trait(BaseModel):
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


def get_traits(conn: duckdb.DuckDBPyConnection) -> list[Trait]:
    stmt = """
        SELECT
            LOWER(TRIM(d.trait)) AS trait,
            LOWER(TRIM(d.data_type)) AS data_type,
            d.label,
            TRIM(d.direction) AS direction,
            d.trait_group,
            d.scale,
            d.valid_min,
            d.valid_max,
            d.synonyms_keywords,
            d.description
        FROM main.trait_dictionary AS d
        WHERE d.agent_enabled = True
        ORDER BY trait
    """

    cursor = conn.cursor()
    cursor.execute(stmt)

    columns = [col[0] for col in cursor.description]
    rows = cursor.fetchall()
    traits = [Trait.model_validate(dict(zip(columns, r))) for r in rows]

    return traits


def is_rankable(trait: Trait) -> bool:
    return trait.data_type == "float" and trait.direction in (
        TraitDirection.High,
        TraitDirection.Low,
    )
