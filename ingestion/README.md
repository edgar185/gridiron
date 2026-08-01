# Data Ingestion — Setup & Scheduling

Three scripts, three sources, mapped to the `refresh_*` stub functions in `fantasy_pipeline_dag.py`. All three gaps flagged earlier are now closed except one, which turned out not to be closable for free — noted below rather than papered over.

| Script | Source | Cost | Fills in |
|---|---|---|---|
| `nflverse_ingest.py` | nflverse (via `nfl_data_py`) | Free | teams, games, players, weekly stats, snap counts |
| `odds_ingest.py` | The Odds API | Free tier (500 credits/mo) → $30/mo for 20K | Vegas lines + player props |
| `weather_ingest.py` | Open-Meteo | Free | Weather for outdoor games |
| `stadiums_seed.sql` | manual (one-time) | Free | 32 stadium coordinates + dome status |

## What changed from the first draft

**1. ID crosswalk — closed, via a schema change.** The original scripts faked IDs (`hash(team_abbr)`, event-id-as-game-id) against `BIGINT` columns, which would have failed outright. Fixed properly: `players.player_id`, `teams.team_id`, and `games.game_id` now use nflverse's own natural keys directly (gsis_id, team abbreviation, and nflverse's `game_id` format) — so nflverse ingestion needs **no** mapping table at all. The Odds API is the one source with a genuinely different identity system (free-text names, its own event ids), so two small crosswalk tables handle just that: `odds_event_map` (event id → `game_id`, matched once by team+kickoff-date and cached) and `player_name_aliases` (fuzzy-matched via stdlib `difflib`, cached with a confidence score, flagged `verified = false` until a human checks it). `nflverse_ingest.py` and `odds_ingest.py` are rewritten against this.

**2. Stadium coordinates — closed.** `stadiums_seed.sql` seeds all 32 stadiums with lat/lon and current dome status for the 2026 season, including the Bills' new Highmark Stadium (opened 2026, still outdoor) — Titans/Jaguars/Browns/Commanders stay at their existing outdoor venues this season; their domed replacements don't open until 2027+.

**3. Route participation — decided against.** True routes-run data isn't in any free nflverse release, and PFF's consumer PFF+ subscription doesn't include API access (their real programmatic option, SportsDataIO's "Discovery Lab" tier, runs ~$99–150/mo). Given the app's actual job — recommend who to draft, start/sit, and pick up — that's a precision upgrade to Stage A, not something the core recommendation depends on. **Decision: skip it.** `route_participation_pct` stays `NULL` permanently rather than pending a future paid integration; `snap_pct` is the accepted, documented proxy for pass-route usage going forward. If this is ever revisited, treat it as a deliberate model-quality upgrade, not a gap to close.

## 1. Setup

```bash
cd ~/gridironiq
mkdir -p ingestion && cp <the 3 .py scripts, stadiums_seed.sql, requirements.txt> ingestion/
python3 -m venv ingest_venv && source ingest_venv/bin/activate
pip install -r ingestion/requirements.txt
```

Add to `.env` (git-ignored):
```
DATABASE_URL=postgresql://gridiron:gridiron_dev@localhost:5432/gridironiq
ODDS_API_KEY=your_key_from_the-odds-api.com
```
```bash
export $(cat .env | xargs)
```

## 2. Run in order

```bash
# 1. Base reference data + this week's stats (free — run this first, always)
python ingestion/nflverse_ingest.py --season 2026 --week 9

# 2. One-time (or whenever a stadium changes)
psql "$DATABASE_URL" -f ingestion/stadiums_seed.sql

# 3. Weather (free, depends on games + stadiums existing)
python ingestion/weather_ingest.py --week 9

# 4. Odds (costs credits — run last, after confirming 1–3 worked)
python ingestion/odds_ingest.py --season 2026 --week 9
```

`nflverse_ingest.py` must run first every time — it populates `games`, which both `weather_ingest.py` and `odds_ingest.py`'s game-matching now depend on.

## 3. Verifying the crosswalks worked

```sql
-- Any unverified player name matches worth a manual glance:
SELECT * FROM player_name_aliases WHERE verified = false ORDER BY confidence ASC;

-- Odds events that failed to match a game (usually a team-name typo in
-- TEAM_NAME_TO_ABBR, or the game isn't in `games` yet):
SELECT odds_event_id FROM odds_event_map; -- compare count against fetch_events() output
```

Low-confidence aliases (below ~0.90) are worth eyeballing before trusting that prop's data — a bad fuzzy match silently attaches one player's Vegas prop to a different player.

## 4. Scheduling — folding into the existing `launchd` / pipeline setup

Ingestion runs *before* the model retrain, so it slots in as new tasks at the front of the weekly DAG from `fantasy_pipeline_dag.py`:

```
ingest_nflverse_stats → seed_stadiums (idempotent, cheap to re-run) → ingest_weather → refresh_trailing_form_view → ... (existing chain)
```

Odds are time-sensitive in a way stats aren't — a Tuesday-morning line is stale by Sunday. Run odds ingestion **twice**:

- Tuesday (with the main weekly retrain) — for early-week waiver/draft context
- Saturday night or Sunday morning — closer-to-kickoff refresh for that week's Start/Sit accuracy, since implied totals and player props move throughout the week

Add a second `launchd` agent (or a second `StartCalendarInterval` entry) for the Sunday odds refresh alongside the existing weekly-Tuesday one — same `.plist` pattern from the setup guide, just pointing at `odds_ingest.py` instead of the full retrain.
