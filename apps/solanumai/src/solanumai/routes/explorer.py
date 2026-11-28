import csv
import io
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from solanumai.contracts import ExplorerOptions, ExplorerPage, ExplorerQuery
from solanumai.db import get_conn

PAGE_SIZE = 50

ID_COLUMNS = ["year", "env_type", "location", "experiment_name", "variety", "plot"]

ROWS_STMT = """
    SELECT *
    FROM intermediate.int_trials AS t
    WHERE (%(env_type)s::text  IS NULL OR env_type = %(env_type)s)
      AND (%(year_from)s::int  IS NULL OR year >= %(year_from)s)
      AND (%(year_to)s::int    IS NULL OR year <= %(year_to)s)
      AND (%(location)s::text  IS NULL OR location ILIKE %(location)s)
      AND (%(variety)s::text   IS NULL OR variety ILIKE %(variety)s)
      AND (%(experiment)s::text IS NULL OR experiment_name ILIKE %(experiment)s)
      AND (%(trait)s::text     IS NULL OR to_jsonb(t) ->> %(trait)s IS NOT NULL)
    ORDER BY year DESC, experiment_name, variety, plot
    LIMIT %(limit)s OFFSET %(offset)s
"""

OPTIONS_STMT = """
    SELECT
        ARRAY(SELECT DISTINCT env_type FROM intermediate.int_trials WHERE env_type IS NOT NULL ORDER BY 1),
        ARRAY(SELECT DISTINCT location FROM intermediate.int_trials WHERE location IS NOT NULL ORDER BY 1),
        (SELECT MIN(year) FROM intermediate.int_trials),
        (SELECT MAX(year) FROM intermediate.int_trials)
"""

router = APIRouter(prefix="/api/explorer", tags=["explorer"])


def _contains(text: str | None) -> str | None:
    # "contains" for ILIKE; note % and _ typed by the user also act as wildcards
    return f"%{text}%" if text else None


@router.get("", response_model=ExplorerPage)
def explore(query: Annotated[ExplorerQuery, Query()], conn=Depends(get_conn)):
    csv_export = query.format == "csv"
    params = {
        "env_type": query.env_type,
        "year_from": query.year_from,
        "year_to": query.year_to,
        "location": _contains(query.location),
        "variety": _contains(query.variety),
        "experiment": _contains(query.experiment),
        "trait": query.trait,
        "limit": None if csv_export else PAGE_SIZE + 1,
        "offset": 0 if csv_export else (query.page - 1) * PAGE_SIZE,
    }

    cur = conn.execute(ROWS_STMT, params)
    names = [d.name for d in cur.description]

    if query.trait and query.trait not in names:
        raise HTTPException(400, f"Unknown trait: {query.trait}")

    traits = sorted(c for c in names if c not in ID_COLUMNS)
    columns = ID_COLUMNS + ([query.trait] if query.trait else traits)
    order = [names.index(c) for c in columns]
    rows = [[r[i] for i in order] for r in cur.fetchall()]

    if csv_export:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(columns)
        writer.writerows(rows)
        return Response(
            content="\ufeff" + buf.getvalue(),  # BOM: Excel opens UTF-8 correctly
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="trial_data.csv"'},
        )

    env_types, locations, year_min, year_max = conn.execute(OPTIONS_STMT).fetchone()

    return ExplorerPage(
        columns=columns,
        rows=rows[:PAGE_SIZE],
        page=query.page,
        page_size=PAGE_SIZE,
        has_next=len(rows) > PAGE_SIZE,
        options=ExplorerOptions(
            env_types=env_types,
            locations=locations,
            year_min=year_min,
            year_max=year_max,
            traits=traits,
        ),
    )
