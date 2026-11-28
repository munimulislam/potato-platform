from dataclasses import dataclass
from typing import Any

import psycopg
import sqlglot
from psycopg import errors as pg_errors
from psycopg import sql
from psycopg_pool import ConnectionPool, PoolTimeout
from sqlglot import exp

from potato_data_agent.config import DEFAULT_SCHEMAS
from potato_data_agent.errors import (
    DatabaseUnavailable,
    QueryFailed,
    QueryTimeout,
    UnsafeQuery,
)

SQL_DENIED_FUNCTIONS = frozenset(
    {
        "set_config",
        "pg_sleep",
        "pg_terminate_backend",
        "pg_cancel_backend",
        "pg_reload_conf",
        "pg_read_file",
        "pg_read_binary_file",
        "pg_ls_dir",
        "pg_stat_file",
        "lo_import",
        "lo_export",
        "dblink",
        "dblink_exec",
    }
)


@dataclass(frozen=True)
class SqlResult:
    columns: list[str]
    rows: list[tuple]


def _function_name(node: exp.Func) -> str:
    return (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).lower()


class SqlRunner:
    def __init__(
        self,
        pool: ConnectionPool,
        *,
        allowed_schemas: frozenset[str] = DEFAULT_SCHEMAS,
    ):
        self._pool = pool
        self._allowed = allowed_schemas

    @property
    def allowed_schemas(self) -> frozenset[str]:
        return self._allowed

    def check(self, query: str) -> None:
        """Raise UnsafeQuery unless `query` is a single SELECT on allowed tables."""
        try:
            statements = [
                s for s in sqlglot.parse(query, read="postgres") if s is not None
            ]
        except sqlglot.errors.ParseError as e:
            raise UnsafeQuery(f"Could not parse the SQL: {e}") from None

        if len(statements) != 1:
            raise UnsafeQuery("Send exactly one SQL statement.")

        stmt = statements[0]

        if not isinstance(stmt, exp.Select):
            raise UnsafeQuery("Only SELECT queries are allowed.")

        for fn in stmt.find_all(exp.Func):
            if _function_name(fn) in SQL_DENIED_FUNCTIONS:
                raise UnsafeQuery(f"Function not allowed: {_function_name(fn)}")

        cte_names = {cte.alias_or_name for cte in stmt.find_all(exp.CTE)}
        for table in stmt.find_all(exp.Table):
            if not table.name:
                continue
            if not table.db and table.name in cte_names:
                continue
            if table.db not in self._allowed:
                raise UnsafeQuery(
                    f"Table not allowed: {table.sql(dialect='postgres')}. "
                )

    def run(self, query: str) -> SqlResult:
        self.check(query)
        return self._execute(query, None)

    def run_trusted(
        self, query: sql.Composable, params: dict[str, Any] | None = None
    ) -> SqlResult:
        return self._execute(query, params)

    def _execute(
        self, query: str | sql.Composable, params: dict[str, Any] | None
    ) -> SqlResult:
        try:
            with self._pool.connection() as conn, conn.cursor() as cur:
                cur.execute(query, params)
                columns = [c.name for c in cur.description] if cur.description else []
                rows = cur.fetchall()
        except PoolTimeout:
            raise DatabaseUnavailable("The database is not reachable.") from None
        except pg_errors.QueryCanceled:
            raise QueryTimeout("The query took a lot of time.") from None
        except psycopg.Error as e:
            message = getattr(getattr(e, "diag", None), "message_primary", None) or str(
                e
            )
            raise QueryFailed(message) from None

        return SqlResult(
            columns=columns,
            rows=rows,
        )
