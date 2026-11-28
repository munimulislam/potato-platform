from pydantic import BaseModel, ConfigDict

from potato_data_agent.common import ENV_LABELS, EnvType, ToolError
from potato_data_agent.context import ToolContext
from potato_data_agent.trait_catalog import (
    Location,
    TraitCoverage,
    TraitDescription,
    get_locations,
    get_trait_coverage,
    get_traits,
    get_year_range,
    is_rankable,
)


class DescribeDataQuery(BaseModel):
    model_config = ConfigDict(extra="ignore")


class TraitInfo(TraitDescription, TraitCoverage):
    pass


class Region(BaseModel):
    code: EnvType
    label: str


class DataDescription(BaseModel):
    traits: list[TraitInfo]
    locations: list[Location]
    env_types: list[Region]
    year_min: int
    year_max: int | None


def describe_data(query: DescribeDataQuery, ctx: ToolContext) -> DataDescription:
    traits = [t for t in get_traits(ctx.sql) if is_rankable(t)]
    coverage = get_trait_coverage(ctx.sql)
    locations = get_locations(ctx.sql)
    year_min, year_max = get_year_range(ctx.sql)

    if not traits:
        raise ToolError("No rankable traits are enabled in trait_dictionary.")
    if year_min is None:
        raise ToolError("No trial data found.")

    return DataDescription(
        traits=[
            TraitInfo(
                **t.model_dump(), **coverage.get(t.trait, TraitCoverage()).model_dump()
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
