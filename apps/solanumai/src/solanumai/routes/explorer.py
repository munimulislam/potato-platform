"""
Data explorer endpoints
"""

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from psycopg import sql
from solanumai.contracts import TableInfo, TablePage
from solanumai.db import get_conn

ALLOWED_SCHEMAS = ["marts", "staging", "intermediate", "reference"]
PAGE_SIZE = 50

router = APIRouter(prefix="/api/tables", tags=["explorer"])


def _columns(conn, schema: str, table: str) -> list[str]:
    if schema not in ALLOWED_SCHEMAS:
        raise HTTPException(404, "Table not found")
    rows = conn.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
        """,
        (schema, table),
    ).fetchall()
    if not rows:
        raise HTTPException(404, "Table not found")
    return [r[0] for r in rows]


def _select(
    schema: str,
    table: str,
    columns: list[str],
    filter_col: str | None,
    filter_val: str | None,
):
    query = sql.SQL("SELECT {cols} FROM {tbl}").format(
        cols=sql.SQL(", ").join(map(sql.Identifier, columns)),
        tbl=sql.Identifier(schema, table),
    )
    params: list = []
    if filter_col and filter_val:
        if filter_col not in columns:
            raise HTTPException(400, f"Unknown column: {filter_col}")
        query += sql.SQL(" WHERE {col}::text ILIKE %s").format(
            col=sql.Identifier(filter_col)
        )
        params.append(f"%{filter_val}%")
    # Order by every column: stable paging
    query += sql.SQL(" ORDER BY {order}").format(
        order=sql.SQL(", ").join(sql.SQL(str(i)) for i in range(1, len(columns) + 1))
    )
    return query, params


@router.get("", response_model=list[TableInfo])
def list_tables(conn=Depends(get_conn)):
    rows = conn.execute(
        """
        SELECT t.table_schema, t.table_name, GREATEST(c.reltuples, 0)::bigint
        FROM information_schema.tables AS t
        JOIN pg_namespace AS n ON n.nspname = t.table_schema
        JOIN pg_class     AS c ON c.relnamespace = n.oid AND c.relname = t.table_name
        WHERE t.table_schema = ANY(%s)
        ORDER BY t.table_schema, t.table_name
        """,
        (ALLOWED_SCHEMAS,),
    ).fetchall()

    return [TableInfo(schema_name=s, table_name=t, approx_rows=n) for s, t, n in rows]


@router.get("/{schema}/{table}", response_model=TablePage)
def read_table(
    schema: str,
    table: str,
    page: int = Query(1, ge=1),
    filter_col: str | None = None,
    filter_val: str | None = None,
    conn=Depends(get_conn),
):
    columns = _columns(conn, schema, table)
    query, params = _select(schema, table, columns, filter_col, filter_val)
    query += sql.SQL(" LIMIT %s OFFSET %s")
    rows = conn.execute(
        query, [*params, PAGE_SIZE + 1, (page - 1) * PAGE_SIZE]
    ).fetchall()

    return TablePage(
        schema_name=schema,
        table_name=table,
        columns=columns,
        rows=[list(r) for r in rows[:PAGE_SIZE]],
        page=page,
        page_size=PAGE_SIZE,
        has_next=len(rows) > PAGE_SIZE,
    )


@router.get("/{schema}/{table}/export")
def export_csv(
    schema: str,
    table: str,
    filter_col: str | None = None,
    filter_val: str | None = None,
    conn=Depends(get_conn),
):
    columns = _columns(conn, schema, table)
    query, params = _select(schema, table, columns, filter_col, filter_val)
    rows = conn.execute(query, params).fetchall()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(columns)
    writer.writerows(rows)

    return Response(
        content="\ufeff" + buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{schema}.{table}.csv"'},
    )
