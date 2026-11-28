ARG PYTHON_VERSION=3.12.10
ARG DEBIAN_RELEASE=bookworm
ARG UV_VERSION=0.13.7                     

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

FROM python:${PYTHON_VERSION}-slim-${DEBIAN_RELEASE} AS base

ARG DEBIAN_RELEASE

ARG R_VERSION=4.6.0
ARG R_OS=debian-12


RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && ARCH="$(dpkg --print-architecture)" \
    && curl -fsSLo /tmp/r.deb "https://cdn.posit.co/r/${R_OS}/pkgs/r-${R_VERSION}_1_${ARCH}.deb" \
    && apt-get install -y --no-install-recommends /tmp/r.deb \
    && ln -s /opt/R/${R_VERSION}/bin/R       /usr/local/bin/R \
    && ln -s /opt/R/${R_VERSION}/bin/Rscript /usr/local/bin/Rscript \
    && rm -f /tmp/r.deb \
    && rm -rf /var/lib/apt/lists/*

RUN printf '%s\n' \
    "options(repos = c(CRAN = 'https://packagemanager.posit.co/cran/__linux__/${DEBIAN_RELEASE}/latest'))" \
    "options(HTTPUserAgent = sprintf('R/%s R (%s)', getRversion(), paste(getRversion(), R.version['platform'], R.version['arch'], R.version['os'])))" \
    >> /opt/R/${R_VERSION}/lib/R/etc/Rprofile.site \
    && Rscript -e "install.packages(c('statgenGxE','statgenSTA','lme4','jsonlite'), Ncpus = parallel::detectCores())" \
    && Rscript -e "library(statgenGxE); library(statgenSTA); library(lme4); library(jsonlite); cat('R', as.character(getRversion()), ': packages OK\n')"

COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    SECRETS_DIR=/run/secrets \
    RSCRIPT_PATH=/usr/local/bin/Rscript

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
RUN useradd --create-home --uid 1000 solanumai && chown -R solanumai:solanumai /app
USER solanumai
ENTRYPOINT ["with-secrets"]