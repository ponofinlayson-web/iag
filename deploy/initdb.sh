#!/bin/sh
# Runs once on first boot of an empty postgres volume (docker-entrypoint-initdb.d).
# The .sql lives OUTSIDE initdb.d (mounted at /opt/initdb) so the entrypoint
# does not also run it itself -- this wrapper is its only executor, and it
# injects the app role password as a psql variable (no cleartext password in git).
set -eu

: "${IAG_APP_DB_PASSWORD:?IAG_APP_DB_PASSWORD is not set}"
: "${POSTGRES_DB:?POSTGRES_DB is not set}"

psql -U "$POSTGRES_USER" \
     -v ON_ERROR_STOP=1 \
     -v app_password="$IAG_APP_DB_PASSWORD" \
     --dbname "$POSTGRES_DB" \
     -f /opt/initdb/initdb.sql
