#!/bin/bash
# Runs automatically ONCE on an empty data volume.
set -euo pipefail

secret() { tr -d '\r\n' < "/run/secrets/$1"; }

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$DB_NAME" \
  -v db_name="$DB_NAME" \
  -v dlt_user="$DLT_USER"             -v dlt_pw="$(secret dlt-password)" \
  -v dbt_user="$DBT_USER"             -v dbt_pw="$(secret dbt-password)" \
  -v dg_user="$DAGSTER_USER"          -v dg_pw="$(secret dagster-password)" \
  -v agent_user="$AGENT_USER"         -v agent_pw="$(secret agent-password)" \
  -v app_user="$APP_USER"             -v app_pw="$(secret app-password)" \
  -v app_owner_user="$APP_OWNER_USER" -v app_owner_pw="$(secret app-owner-password)" \
  -f /init/init.sql