"""
SolanumAI web app entry point.
Run: uvicorn solanumai.main:app --host 0.0.0.0 --port 8000
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from potato_data_agent import AgentConfig, OpenAILLM, ToolContext
from starlette.middleware.sessions import SessionMiddleware

from solanumai.agent_runner import AgentRunner
from solanumai.auth import (
    NotAuthenticated,
    configure_auth,
    not_authenticated_handler,
    require_login,
)
from solanumai.auth import router as auth_router
from solanumai.contracts import ModelStatus
from solanumai.db import create_db_pool, create_read_only_db_pool
from solanumai.model_catalog import ModelCatalog, get_catalog
from solanumai.routes import chat, explorer, pages, predict
from solanumai.settings import get_settings
from solanumai.store import ChatStore, PredictionStore
from solanumai.templating import templates

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    app.state.db_pool = create_db_pool(settings)
    app.state.db_pool.open(wait=False)
    app.state.predictions = PredictionStore(app.state.db_pool)
    app.state.chats = ChatStore(app.state.db_pool)

    # Data agent
    app.state.agent_pool = create_read_only_db_pool(settings)
    app.state.agent_pool.open(wait=False)
    agent_config = AgentConfig(
        model=settings.llm_model,
        api_key=settings.llm_api_key.get_secret_value(),
        base_url=settings.llm_base_url,
        temperature=settings.llm_temperature,
        timeout_seconds=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        no_think=settings.llm_no_think,
        rscript_path=settings.rscript_path,
        run_log_path=None,
    )

    app.state.agent_runner = AgentRunner(
        OpenAILLM(agent_config),
        ToolContext.create(app.state.agent_pool, agent_config),
        settings.agent_max_concurrent,
        settings.agent_warm_up_retry_seconds,
    )

    if settings.agent_warm_up:
        app.state.agent_runner.start()

    app.state.catalog = ModelCatalog(settings)
    app.state.catalog.start()

    log.info(
        "SolanumAI started: env=%s password=%s microsoft=%s",
        settings.app_env,
        settings.auth_password_enabled,
        settings.microsoft_enabled,
    )

    yield

    app.state.agent_runner.stop()
    app.state.catalog.stop()
    app.state.db_pool.close()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_auth(settings)
    templates.env.globals.update(
        app_name=settings.app_name,
        password_enabled=settings.auth_password_enabled,
        microsoft_enabled=settings.microsoft_enabled,
    )

    dev = settings.app_env == "dev"
    app = FastAPI(
        title=settings.app_name,
        lifespan=lifespan,
        docs_url="/docs" if dev else None,
        redoc_url=None,
        openapi_url="/openapi.json" if dev else None,
    )

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret.get_secret_value(),
        session_cookie="solanumai_session",
        max_age=settings.session_max_age_seconds,
        same_site="lax",
        https_only=settings.cookie_secure,
    )

    app.add_exception_handler(NotAuthenticated, not_authenticated_handler)

    app.mount(
        "/static",
        StaticFiles(directory=Path(__file__).parent / "static"),
        name="static",
    )

    app.include_router(auth_router)
    protected = [Depends(require_login)]

    for router in (pages.router, predict.router, explorer.router, chat.router):
        app.include_router(router, dependencies=protected)

    @app.get("/health", include_in_schema=False)
    def health():
        return {"status": "ok"}

    @app.get(
        "/api/models/status", response_model=list[ModelStatus], dependencies=protected
    )
    def models_status(catalog: ModelCatalog = Depends(get_catalog)):
        return catalog.status()

    return app


app = create_app()
