#!/bin/bash
# Scheduled data refresh: real ESPN roster sync, nflverse stats, and Vegas
# game lines, run against whichever season/week the real schedule says is
# current -- see resolve_week.py. Installed as a launchd job (see
# scripts/README.md); safe to run by hand too.
set -euo pipefail
cd "$(dirname "$0")/.."

LEAGUE_ID=1859403384  # real synced ESPN league (see ingestion/espn_ingest.py)

mkdir -p logs
LOG_FILE="logs/refresh_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1
echo "=== GridironIQ live refresh: $(date) ==="

set -a
source .env
set +a

DB_URL_INTERNAL="postgresql://gridiron:${POSTGRES_PASSWORD:-gridiron_dev}@db:5432/gridironiq"
NETARGS="--rm --network gridiron_default -e DATABASE_URL=$DB_URL_INTERNAL"

WEEKS=$(docker run $NETARGS -v "$(pwd)/scripts:/app" -w /app python:3.11-slim bash -c \
  "pip install -q psycopg[binary] >/dev/null 2>&1; python resolve_week.py")
eval "$WEEKS"
echo "Resolved: season=$SEASON current_week=$CURRENT_WEEK stats_week=$STATS_WEEK"

echo "--- ESPN roster/free-agent sync ---"
docker run $NETARGS --env-file .env -v "$(pwd)/ingestion:/app" -w /app python:3.11-slim bash -c \
  "pip install -q psycopg[binary] espn_api >/dev/null 2>&1; python espn_ingest.py --season $SEASON --league-id $LEAGUE_ID"

if [ "$STATS_WEEK" -ge 1 ]; then
  echo "--- nflverse weekly stats (week $STATS_WEEK) ---"
  docker run $NETARGS -v "$(pwd)/ingestion:/app" -w /app python:3.11-slim bash -c \
    "pip install -q psycopg[binary] pandas pyarrow nfl_data_py >/dev/null 2>&1; python nflverse_ingest.py --season $SEASON --week $STATS_WEEK"
else
  echo "--- nflverse stats: season hasn't started yet (stats_week=0) -- skipping ---"
fi

echo "--- Odds: game lines only (player props stay manual -- see odds_ingest.py --skip-props) ---"
docker run $NETARGS -e ODDS_API_KEY="${ODDS_API_KEY:-}" -v "$(pwd)/ingestion:/app" -w /app python:3.11-slim bash -c \
  "pip install -q psycopg[binary] requests >/dev/null 2>&1; python odds_ingest.py --season $SEASON --week $CURRENT_WEEK --skip-props"

if [ "$STATS_WEEK" -ge 1 ]; then
  echo "--- v1 projections (through week $STATS_WEEK, target week $CURRENT_WEEK) ---"
  docker run $NETARGS -v "$(pwd)/pipeline:/app" -w /app python:3.11-slim bash -c \
    "pip install -q psycopg[binary] >/dev/null 2>&1; python v1_projections.py --season $SEASON --through-week $STATS_WEEK --target-week $CURRENT_WEEK --league-id $LEAGUE_ID"
fi

echo "=== Done: $(date) ==="
