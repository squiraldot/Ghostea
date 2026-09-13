#!/bin/sh
set -eu

: "${DATABASE_URL:?DATABASE_URL is required}"
SCHEMA_FILE="${1:-database.sql}"

case "$DATABASE_URL" in
  postgresql://*|postgres://*) ;;
  *) echo "DATABASE_URL must be a PostgreSQL URL" >&2; exit 1 ;;
esac

command -v psql >/dev/null 2>&1 || {
  echo "psql is required. Install the PostgreSQL client first." >&2
  exit 1
}

echo "Applying Ghostea schema from ${SCHEMA_FILE}..."
psql "$DATABASE_URL" --set ON_ERROR_STOP=1 --file "$SCHEMA_FILE"
echo "Schema applied successfully."
