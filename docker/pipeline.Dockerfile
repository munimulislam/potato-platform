# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.12.10
ARG DEBIAN_RELEASE=bookworm 
ARG UV_VERSION=0.13.7                     

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

FROM python:${PYTHON_VERSION}-slim-${DEBIAN_RELEASE} AS base
ARG DEBIAN_RELEASE

RUN apt-get update && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    DAGSTER_HOME=/opt/dagster/dagster_home \
    DLT_HOME=/opt/dagster/dlt \
    DBT_PROJECT_DIR=/app/apps/dbt/transformation \
    DBT_PROFILES_DIR=/app/apps/dbt/transformation \
    PIPELINE_DATA_DIR=/data \
    SECRETS_DIR=/run/secrets

WORKDIR /app
COPY docker/with-secrets.sh /usr/local/bin/with-secrets
RUN chmod +x /usr/local/bin/with-secrets

FROM base AS source
COPY pyproject.toml uv.lock ./
COPY packages/ packages/
COPY apps/pipeline/ apps/pipeline/
COPY apps/dbt/ apps/dbt/
COPY apps/pipeline/dg_home/dagster.yaml ${DAGSTER_HOME}/dagster.yaml
COPY apps/pipeline/dg_home/workspace.yaml ${DAGSTER_HOME}/workspace.yaml

FROM source AS dev
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --package potato_pipeline
EXPOSE 3000
ENTRYPOINT ["with-secrets"]
CMD ["dagster", "dev", "-h", "0.0.0.0", "-p", "3000"]

FROM source AS prod
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package pipeline

EXPOSE 3000
ENTRYPOINT ["with-secrets"]
CMD ["dagster-webserver", "-h", "0.0.0.0", "-p", "3000"]