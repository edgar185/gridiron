# Running GridironIQ Locally on a Mac Mini

Everything we've built maps to four pieces that need to run on your machine: a **database** (the schema), a **backend API** (the contracts), a **frontend** (the wireframes), and a **scheduler** (the pipeline). Here's the lightest stack that gets all four running locally — updated to run backend and frontend as Docker containers alongside Postgres, so `restart: unless-stopped` keeps everything alive with no separate process-management layer.

## Recommended local stack

| Piece | What we spec'd | Local tool |
|---|---|---|
| Database | `fantasy_kpi_schema.sql` | PostgreSQL via Docker |
| Backend | `api-contracts.md` | Python + FastAPI, containerized |
| Frontend | the `.jsx` wireframes | Vite + React, containerized |
| Scheduler | `fantasy_pipeline_dag.py` | **macOS `launchd`**, not Airflow |

All three services live in one `docker-compose.yml` with `restart: unless-stopped` — that single policy is now doing the "keep it running" job, so there's no separate `launchd` agent needed just to keep processes alive (see the auto-restart guide for how that piece simplified too).

On Airflow specifically: it's the right call once you have a team and a server running 24/7. For one person on a Mac mini, it's a lot of overhead (its own metadata DB, a webserver, a scheduler process) for two jobs a week. `launchd` (macOS's native scheduler — think "cron, but Apple's version") runs your existing Python scripts on the same weekly/monthly schedule with far less to maintain. You can swap in real Airflow later without changing the job code itself, since the task functions in `fantasy_pipeline_dag.py` don't know or care what's calling them.

---

## 1. Prerequisites

```bash
# Homebrew, if you don't have it
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Docker Desktop for Mac (handles Postgres cleanly, esp. on Apple Silicon)
brew install --cask docker
```

Open Docker Desktop once from Applications, then go to **Settings → General → "Start Docker Desktop when you log in"** and enable it — this replaces the need for any login script to launch Docker for you.

Node and Python are no longer required on the host directly — they only run inside the containers now. You can skip installing them locally unless you want to run scripts outside Docker for quick iteration.

## 2. Project layout

```bash
mkdir -p ~/gridironiq/{backend,frontend} && cd ~/gridironiq
```

Copy `fantasy_kpi_schema.sql` from this chat's outputs into `~/gridironiq/`.

## 3. `docker-compose.yml` — all three services

```yaml
services:
  db:
    image: postgres:16
    restart: unless-stopped
    environment:
      POSTGRES_USER: gridiron
      POSTGRES_PASSWORD: gridiron_dev
      POSTGRES_DB: gridironiq
    ports: ["5432:5432"]
    volumes:
      - gridironiq_pgdata:/var/lib/postgresql/data
      - ./fantasy_kpi_schema.sql:/docker-entrypoint-initdb.d/schema.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U gridiron"]
      interval: 5s
      retries: 5

  backend:
    build: ./backend
    restart: unless-stopped
    ports: ["8000:8000"]
    depends_on:
      db:
        condition: service_healthy
    environment:
      DATABASE_URL: postgresql://gridiron:gridiron_dev@db:5432/gridironiq

  frontend:
    build: ./frontend
    restart: unless-stopped
    ports: ["5173:5173"]
    depends_on: [backend]

volumes:
  gridironiq_pgdata:
```

Mounting `fantasy_kpi_schema.sql` into Postgres's `docker-entrypoint-initdb.d/` means the schema loads automatically the first time the `db` container starts — no manual `psql` step needed.

## 4. Backend — FastAPI, containerized

`backend/requirements.txt`:
```
fastapi
uvicorn[standard]
psycopg[binary]
```

`backend/main.py` — one endpoint from `api-contracts.md` to prove the wiring works end to end, before you build the rest:

```python
import os
from fastapi import FastAPI
import psycopg
from psycopg.rows import dict_row

app = FastAPI()
DB_URL = os.environ["DATABASE_URL"]

@app.get("/v1/players/{player_id}/card")
def player_card(player_id: int, week: int, scoring: str = "ppr"):
    with psycopg.connect(DB_URL, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            SELECT p.player_id, p.full_name AS name, p.position, t.abbreviation AS team,
                   pr.floor_pts, pr.median_pts, pr.ceiling_pts, pr.confidence_score,
                   pr.recommendation, pr.rationale_text
            FROM players p
            JOIN teams t ON t.team_id = p.team_id
            LEFT JOIN projections pr
              ON pr.player_id = p.player_id AND pr.week = %s
            WHERE p.player_id = %s
            """,
            (week, player_id),
        ).fetchone()
    return row or {"error": {"code": "PLAYER_NOT_FOUND"}}
```

`backend/Dockerfile`:
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

From here, add one endpoint per section of `api-contracts.md` — `/compare`, `/draft/tiers`, `/waivers/candidates` — following the same pattern. Rebuild after changes with `docker compose build backend`.

## 5. Frontend — Vite + React, containerized

```bash
cd ~/gridironiq
npm create vite@latest frontend -- --template react
cd frontend
npm install lucide-react
npm install -D tailwindcss postcss autoprefixer
npx tailwindcss init -p
```

Copy `gridiron-app-demo.jsx` (or the individual `player-card-wireframe.jsx` / `draft-tier-board-wireframe.jsx`) into `frontend/src/App.jsx`, make sure `tailwind.config.js` content globs cover `./src/**/*.{js,jsx}`, and add the Tailwind directives to `src/index.css`:

```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

`frontend/Dockerfile`:
```dockerfile
FROM node:20-slim
WORKDIR /app
COPY package*.json .
RUN npm install
COPY . .
CMD ["npm", "run", "dev", "--", "--host"]
```

`--host` is required — without it, Vite's dev server only binds to localhost *inside* the container and won't be reachable from your Mac's browser.

Currently the components use hardcoded mock arrays (`CARD_PLAYERS`, `TIERS_WR`, etc.) — swap those for `fetch("http://localhost:8000/v1/...")` calls once the backend endpoints above are live.

## 6. Scheduler — `launchd` for the weekly/monthly jobs

This piece is unchanged — the model pipeline stays outside Docker since it's calendar-triggered, not always-on. Convert the task functions in `fantasy_pipeline_dag.py` into a couple of plain scripts (`weekly_retrain.py`, `monthly_recalibration.py`) that just call the functions in sequence — no Airflow decorators needed, since `launchd` handles the "when," not the DAG library. (If those scripts need to reach Postgres, connect to `localhost:5432`, since the `db` container's port is published to the host.)

Save as `~/Library/LaunchAgents/com.gridironiq.weekly.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.gridironiq.weekly</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/YOUR_USERNAME/gridironiq/venv/bin/python3</string>
    <string>/Users/YOUR_USERNAME/gridironiq/pipeline/weekly_retrain.py</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Weekday</key><integer>2</integer> <!-- Tuesday -->
    <key>Hour</key><integer>6</integer>
    <key>Minute</key><integer>0</integer>
  </dict>
  <key>StandardOutPath</key><string>/tmp/gridironiq-weekly.log</string>
  <key>StandardErrorPath</key><string>/tmp/gridironiq-weekly.err</string>
</dict>
</plist>
```

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.gridironiq.weekly.plist
```

Note: the Mac mini has to be **awake** at 6am Tuesday for this to fire — either disable sleep in System Settings → Energy, or use `pmset` to schedule a wake:

```bash
sudo pmset repeat wakeorpoweron TU 05:55:00
```

Duplicate the `.plist` for the monthly job with `StartCalendarInterval` set to `Day: 1` instead of `Weekday`.

---

## Running it day to day

```bash
cd ~/gridironiq
docker compose up -d
```

That's it — one command. All three services keep themselves alive via `restart: unless-stopped`, and Docker Desktop autostarts at login (step 1), so after initial setup you shouldn't need to touch a terminal at all for normal day-to-day use. Check status or logs anytime with:

```bash
docker compose ps
docker compose logs -f backend
```

---

## When to graduate off this

- **Multiple users hitting the app** → move Postgres + FastAPI to a small cloud VM or managed Postgres (e.g., Supabase/RDS), keep the Mac mini for model training only
- **Pipeline jobs need retries/alerting/visibility** → that's the point where the real `fantasy_pipeline_dag.py` (Airflow) earns its keep over `launchd`
- **Data volume grows** (years of play-by-play) → Postgres is still fine, but you'll want the `player_trailing_form` materialized view refresh to run on a schedule separate from the full weekly retrain
