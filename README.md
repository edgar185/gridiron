# GridironIQ

A fantasy football decision engine for three calls: **Draft**, **Start/Sit**, and **Waiver/Pickup**. Everything in this repo exists to turn raw NFL data into a confidence-scored recommendation with a plain-language reason, for one of those three moments.

## Structure

```
schema/       PostgreSQL DDL + stadium seed data
ingestion/    Data pull scripts (nflverse, The Odds API, Open-Meteo)
pipeline/     Airflow DAG sketch for weekly retrain / monthly recalibration
backend/      FastAPI service implementing docs/02-api-contracts.md
frontend/     React (Vite) app — draft board, start/sit comparator, waiver finder
docs/         Full spec set — read these in order for context
```

## Docs (read in order)

1. [Feature roadmap](docs/01-feature-roadmap.md) — what the app does, KPI list, external data sources
2. [API contracts](docs/02-api-contracts.md) — endpoint shapes, backed by the schema
3. [Projection model spec](docs/03-projection-model-spec.md) — how floor/median/ceiling/confidence are computed
4. [Pipeline architecture](docs/04-pipeline-architecture.md) — job DAG, retry/gating logic
5. [Local setup guide](docs/05-local-setup-guide.md) — running the whole stack on a Mac
6. [Auto-restart guide](docs/06-auto-restart-guide.md) — keeping it running unattended

See [`ingestion/README.md`](ingestion/README.md) for data-source setup, costs, and known limitations (route participation is intentionally not tracked — see that doc for why).

## Quickstart

```bash
cp .env.example .env   # fill in ODDS_API_KEY and a real POSTGRES_PASSWORD
docker compose up -d
```

Backend: http://localhost:8000/docs · Frontend: http://localhost:5173

Then run ingestion once to populate real data (see `ingestion/README.md`):

```bash
python3 -m venv ingest_venv && source ingest_venv/bin/activate
pip install -r ingestion/requirements.txt
export $(cat .env | xargs)
python ingestion/nflverse_ingest.py --season 2026 --week 9
python ingestion/weather_ingest.py --season 2026 --week 9
python ingestion/odds_ingest.py --season 2026 --week 9
```

## Status

Scaffolding is real and runnable (Docker stack, one working API endpoint, ingestion scripts, schema). The model itself (`docs/03-projection-model-spec.md`) is a spec, not yet implemented — `projections` table will be empty until that's built.
