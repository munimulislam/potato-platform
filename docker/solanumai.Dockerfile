# syntax=docker/dockerfile:1
ARG PYTHON_VERSION=3.12.10
ARG DEBIAN_RELEASE=bookworm
ARG UV_VERSION=0.13.7

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

FROM python:${PYTHON_VERSION}-slim-${DEBIAN_RELEASE} AS base

RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" SECRETS_DIR=/run/secrets

WORKDIR /app
COPY docker/with-secrets.sh /usr/local/bin/with-secrets

RUN chmod +x /usr/local/bin/with-secrets

FROM base AS source
COPY pyproject.toml uv.lock ./
COPY packages/ packages/
COPY apps/solanumai/ apps/solanumai/

FROM source AS dev
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --package solanumai
ENTRYPOINT ["with-secrets"]

FROM source AS prod
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --package solanumai
ENTRYPOINT ["with-secrets"]