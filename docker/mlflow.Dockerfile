# syntax=docker/dockerfile:1
ARG PYTHON_VERSION=3.12.10
ARG DEBIAN_RELEASE=bookworm
FROM python:${PYTHON_VERSION}-slim-${DEBIAN_RELEASE}

ARG MLFLOW_VERSION
RUN test -n "$MLFLOW_VERSION" || (echo "Set MLFLOW_VERSION in .env.<env> (same as uv.lock)" >&2; exit 1)
RUN pip install --no-cache-dir "mlflow==${MLFLOW_VERSION}" "psycopg2-binary>=2.9,<3"

COPY docker/with-secrets.sh /usr/local/bin/with-secrets

ENV SECRETS_DIR=/run/secrets

EXPOSE 5000

ENTRYPOINT ["with-secrets"]