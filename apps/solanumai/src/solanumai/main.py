"""
SolanumAI web app: entry point.

Run: uvicorn solanumai.main:app --host 0.0.0.0 --port 8000
"""

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from starlette.middleware.sessions import SessionMiddleware

from solanumai import store
from solanumai.auth import (
    NotAuthenticated,
    configure_auth,
    not_authenticated_handler,
    require_login,
)
from solanumai.auth import router as auth_router
from solanumai.db import create_pool
from solanumai.model_store import load_live_models
from solanumai.routes import chat, pages, predict, tables
from solanumai.settings import get_settings
from solanumai.templating import templates

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs once at start and once at shutdown (replaces the deprecated @app.on_event('startup'))."""
    settings = get_settings()
    store.init_db()
    app.state.models = load_live_models(settings)
    app.state.pool = create_pool(settings)
    app.state.pool.open(
        wait=False
    )  # the app starts even if Postgres is a few seconds late
    log.info(
        "SolanumAI started: env=%s auth=%s models=%s",
        settings.app_env,
        settings.auth_mode,
        sorted(app.state.models),
    )
    yield
    app.state.pool.close()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_auth(settings)
    templates.env.globals.update(
        app_name=settings.app_name, auth_mode=settings.auth_mode
    )

    dev = settings.app_env == "dev"
    app = FastAPI(
        title=settings.app_name,
        lifespan=lifespan,
        # The API docs list every endpoint: useful in dev, not something to publish in prod.
        docs_url="/docs" if dev else None,
        redoc_url=None,
        openapi_url="/openapi.json" if dev else None,
    )

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret.get_secret_value(),
        session_cookie="solanumai_session",
        max_age=settings.session_max_age_seconds,
        same_site="lax",  # cookie not sent with cross-site POSTs: basic CSRF protection
        https_only=settings.cookie_secure,
    )
    app.add_exception_handler(NotAuthenticated, not_authenticated_handler)

    # Public: login, logout, health. Everything else requires a signed-in user.
    app.include_router(auth_router)
    protected = [Depends(require_login)]
    app.include_router(pages.router, dependencies=protected)
    app.include_router(predict.router, dependencies=protected)
    app.include_router(tables.router, dependencies=protected)
    app.include_router(chat.router, dependencies=protected)

    @app.get("/health", include_in_schema=False)
    def health():
        return {"status": "ok"}

    @app.get("/health/db", include_in_schema=False)
    def health_db(request: Request):
        with request.app.state.pool.connection() as conn:
            conn.execute("SELECT 1")
        return {"status": "ok"}

    return app


app = create_app()
