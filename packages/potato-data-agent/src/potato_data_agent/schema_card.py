"""
@File        - schema_card.py
@Description - The description of the database that goes into the system prompt: tables,
               columns with notes, rankable traits, regions, locations, years and the SQL rules.

Built from the database (via catalog.py) on every question, so it never goes out of date.
Text only: the facts come from catalog, the prompt is assembled in loop.py.
"""

from psycopg import sql

from potato_data_agent.common import ENV_LABELS
from potato_data_agent.context import ToolContext
from potato_data_agent.trait_catalog import (
    get_locations,
    get_traits,
    get_year_range,
    is_rankable,
)

TABLES = {
    "intermediate.int_trait_experiment_level": (
        "one row per variety x trial x trait; value = the variety's mean over its plots in that trial"
    ),
    "reference.trait_dictionary": "one row per trait: meaning, scale, direction",
}

COLUMN_NOTES = {
    "variety": "the variety, lowercase; users also say clone, cultivar, genotype, line",
    "experiment_name": (
        "the trial; users also say experiment, field trial; count trials with COUNT(DISTINCT experiment_name)"
    ),
    "trait": (
        "trait name, lowercase, e.g. o_a_score; users also say characteristic, attribute, metric, measurement"
    ),
    "year": "trial year; users also say season",
    "env_type": (
        "region; users also say environment, environment type, env group, zone; "
        "'ne' = North Europe (users may say northern, north), "
        "'med' = Mediterranean (users may say southern, south)"
    ),
    "location": "trial location, lowercase; users also say site, trial site, place, station",
    "value": "the trait value (score or measurement); can be NULL, so filter with value IS NOT NULL",
    "n_plots": "number of plots behind the value",
    "direction": "High = higher is better, Low = lower is better",
    "agent_enabled": "only use traits where this is TRUE",
}

SQL_RULES = """\
SQL rules:
- PostgreSQL. Always write tables with their schema, exactly as listed above
  (intermediate.int_trait_experiment_level, reference.trait_dictionary).
- Text values are lowercase: WHERE location = 'oak park'.
- Always add value IS NOT NULL when counting or averaging values.
- Trials: COUNT(DISTINCT experiment_name). Varieties: COUNT(DISTINCT variety).
- Variety names are not always written the same way; match parts with ILIKE '%name%'.
- ROUND needs numeric: ROUND(AVG(value)::numeric, 2). Percentages: 100.0 * a / b (integer division truncates).
- Median and percentiles: percentile_cont(0.5) WITHIN GROUP (ORDER BY value).
  A list of values: string_agg(DISTINCT location, ', ' ORDER BY location).
- Not available in PostgreSQL: MEDIAN, QUANTILE_CONT, LIST, QUALIFY, GROUP BY ALL, SELECT * EXCLUDE.
- Return few rows: aggregate (GROUP BY) instead of listing raw rows. At most 50 rows come back.
- Never rank or compare varieties with AVG(value): averages ignore how hard each trial was.
  Use rank_varieties for any "best", "top" or "compare" question."""

_COLUMNS = sql.SQL("""
    SELECT table_schema || '.' || table_name, column_name, data_type
    FROM information_schema.columns
    WHERE table_schema || '.' || table_name = ANY(%(tables)s)
    ORDER BY table_name, ordinal_position
""")


def schema_card(ctx: ToolContext) -> str:
    columns = ctx.sql.run_trusted(_COLUMNS, {"tables": list(TABLES)}).rows
    traits = [t for t in get_traits(ctx.sql) if is_rankable(t)]
    locations = get_locations(ctx.sql)
    year_min, year_max = get_year_range(ctx.sql)

    lines = ["# Database (for run_sql)"]

    for table, about in TABLES.items():
        lines.append(f"{table}: {about}")
        for t, column, data_type in columns:
            if t == table:
                note = COLUMN_NOTES.get(column, "")
                lines.append(f"  {column} {data_type}" + (f" - {note}" if note else ""))

    lines.append(
        "Traits that rank_varieties accepts: "
        + "; ".join(f"{t.trait} ({t.label}, {t.direction.value})" for t in traits)
    )
    lines.append(
        "Regions (env_type): "
        + ", ".join(f"{code.value} = {label}" for code, label in ENV_LABELS.items())
    )
    lines.append(
        "Locations (region): "
        + ", ".join(
            f"{loc.location} ({loc.env_type.value})" if loc.env_type else loc.location
            for loc in locations
        )
    )
    lines.append(f"Years: {year_min} to {year_max}")
    lines.append(SQL_RULES)

    return "\n".join(lines)
