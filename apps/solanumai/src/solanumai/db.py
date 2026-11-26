from fastapi import Request
from psycopg.conninfo import make_conninfo
from psycopg_pool import ConnectionPool

from solanumai.settings import Settings


def _conninfo(
    settings: Settings, user: str, password: str, read_only: bool = False
) -> str:
    options = "-c statement_timeout=30000"

    if read_only:
        options += " -c default_transaction_read_only=on"

    return make_conninfo(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=user,
        password=password,
        sslmode=settings.db_sslmode,
        application_name="solanumai",
        options=options,
    )


def create_db_pool(settings: Settings) -> ConnectionPool:
    conninfo = _conninfo(
        settings, settings.app_user, settings.app_password.get_secret_value()
    )
    return ConnectionPool(conninfo=conninfo, min_size=1, max_size=5, open=False)


def get_conn(request: Request):
    with request.app.state.db_pool.connection() as conn:
        yield conn
