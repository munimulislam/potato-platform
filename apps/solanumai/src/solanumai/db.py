"""Read-only Postgres connections for the explorer and the agent."""

from fastapi import Request
from psycopg.conninfo import make_conninfo
from psycopg_pool import ConnectionPool

from solanumai.settings import Settings


def create_pool(settings: Settings) -> ConnectionPool:
    conninfo = make_conninfo(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.agent_user,
        password=settings.agent_password.get_secret_value(),
        sslmode=settings.db_sslmode,
        application_name="solanumai",
        options="-c default_transaction_read_only=on -c statement_timeout=30000",
    )

    return ConnectionPool(conninfo=conninfo, min_size=1, max_size=5, open=False)


def get_conn(request: Request):
    """Dependency: a pooled connection for one request, returned to the pool afterwards."""
    with request.app.state.pool.connection() as conn:
        yield conn
