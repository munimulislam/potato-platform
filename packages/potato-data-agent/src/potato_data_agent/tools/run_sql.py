import datetime as dt
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from potato_data_agent.common import ToolError
from potato_data_agent.context import ToolContext
from potato_data_agent.errors import QueryFailed, QueryTimeout, UnsafeQuery


class RunSqlQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sql: str = Field(min_length=1, description="One PostgreSQL SELECT statement")


class RunSqlResult(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    n_rows: int


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    return value


def run_sql(query: RunSqlQuery, ctx: ToolContext) -> RunSqlResult:
    try:
        result = ctx.sql.run(query.sql)
    except (UnsafeQuery, QueryTimeout, QueryFailed) as e:
        raise ToolError(str(e)) from None

    rows = [[_plain(v) for v in row] for row in result.rows]
    return RunSqlResult(columns=result.columns, rows=rows, n_rows=len(rows))
