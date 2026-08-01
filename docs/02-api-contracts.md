# API Contracts — Schema → UI Data Flow

Conventions: REST/JSON, camelCase in responses (snake_case in DB), `Authorization: Bearer <token>`, all endpoints versioned under `/v1`. Every response includes `generatedAt` for cache/freshness display.

---

## 1. `GET /v1/players/{playerId}/card`

Powers the **Player Card** (Start/Sit view).

**Query params:** `week`, `season`, `scoring` (`std`|`half_ppr`|`ppr`)

**Backing tables:** `projections` (floor/median/ceiling/confidence/rationale) + `defense_matchup_grades` (matchup) + `weather` (join via `games`) + `player_trailing_form` (mat. view, trend sparkline) + `player_game_stats` (raw KPI drawer)

```json
{
  "playerId": 8281,
  "name": "J. CHASE",
  "position": "WR",
  "team": "CIN",
  "jerseyNumber": 1,
  "opponent": "PIT",
  "week": 9,
  "recommendation": "START",
  "confidence": 88,
  "projection": { "floor": 11.2, "median": 18.4, "ceiling": 27.1 },
  "matchup": {
    "vsPositionRank": 27,
    "note": "PIT ranks 27th vs WR (EPA/target)"
  },
  "weather": null,
  "rationale": "Target share up to 31% over the last 3 weeks and PIT's slot coverage has allowed the 5th-most YPRR to WRs.",
  "trend": {
    "metric": "targetShare",
    "points": [0.21, 0.24, 0.26, 0.29, 0.31]
  },
  "kpis": {
    "snapPct": 91.0,
    "routePct": 94.0,
    "targetsPerGame": 9.4,
    "targetShare": 31.0,
    "yprr": 2.61,
    "adot": 12.8,
    "wopr": 0.71,
    "rzTargetsPerGame": 2.1
  },
  "generatedAt": "2026-07-31T14:02:00Z"
}
```

**Server-side derivation notes:**
- `confidence` = model output stored directly in `projections.confidence_score`
- `matchup.vsPositionRank` = `defense_matchup_grades.positional_rank` for opponent team, current week, `vs_position = 'WR'`
- `weather` = null unless `stadiums.is_dome = false`, then pulled from `weather` joined on `game_id`
- `trend.points` = last 5 values of `player_trailing_form.target_share_trail3` (or raw per-week values, model's choice)

---

## 2. `GET /v1/compare?playerIds=8281,4410&week=9&scoring=ppr`

Powers the **comparator "Edge" bar**. Returns two card payloads (shape above) plus a diff object.

```json
{
  "players": ["<card payload A>", "<card payload B>"],
  "edge": {
    "winnerId": 8281,
    "confidenceGap": 54,
    "summary": "Start J. CHASE over T. LOCKETT — 54 pt confidence gap"
  },
  "generatedAt": "2026-07-31T14:02:00Z"
}
```

---

## 3. `GET /v1/draft/tiers`

Powers the **Draft Tier Board**.

**Query params:** `position` (`ALL`|`QB`|`RB`|`WR`|`TE`), `scoring`, `leagueSize`, `draftId` (optional — for live-pick-aware VONA)

**Backing tables:** `projections` (season-long) → VBD calc against `adp` baseline; `adp` for market ADP; `draft_picks_until_turn` (view over `draft_order` + `draft_picks`) for "picks until your turn"; `draft_picks` for VONA (players already off the board).

```json
{
  "position": "WR",
  "picksUntilYourTurn": 4,
  "tiers": [
    {
      "tier": 1,
      "label": "Elite WR1",
      "players": [
        {
          "playerId": 8281,
          "name": "J. CHASE",
          "team": "CIN",
          "adp": 4.2,
          "vbd": 142.6,
          "vona": 38.1,
          "projectedPts": 289.4,
          "valueFlag": "FAIR"
        }
      ]
    },
    {
      "tier": 2,
      "label": "Strong WR1/WR2",
      "players": [
        { "playerId": 5210, "name": "A. BROWN", "team": "PHI", "adp": 11.8, "vbd": 118.3, "vona": 22.4, "projectedPts": 271.0, "valueFlag": "REACH" },
        { "playerId": 6032, "name": "G. WILSON", "team": "NYJ", "adp": 14.1, "vbd": 109.7, "vona": 19.9, "projectedPts": 264.2, "valueFlag": "VALUE" }
      ]
    }
  ],
  "generatedAt": "2026-07-31T14:02:00Z"
}
```

**Server-side derivation notes:**
- `vbd` = `projections.median_pts` (season total) minus replacement-level baseline for the position/league-size
- `vona` = player's VBD minus the VBD of the next player likely available at `picksUntilYourTurn`
- `valueFlag` = `REACH` if current-pick-number < `adp.avg_pick` - threshold, `VALUE` if >, else `FAIR`
- Tiers computed via statistical gap clustering on `median_pts` — not fixed rank cutoffs (recompute on each ADP refresh)

---

## 4. `GET /v1/waivers/candidates`

Powers the **Waiver Wire Finder**.

**Query params:** `leagueId`, `week`, `position` (optional)

**Backing tables:** `player_trailing_form` (usage trend), `depth_charts` (vacancy detection), `injuries` (opens-opportunity flag), `news_events` (trending)

```json
{
  "week": 9,
  "candidates": [
    {
      "playerId": 9921,
      "name": "R. WHITE",
      "position": "RB",
      "team": "TB",
      "rosteredPct": 41.2,
      "trend": { "metric": "snapPct", "points": [0.22, 0.31, 0.44, 0.58, 0.63] },
      "breakoutScore": 82,
      "vacancyReason": "Starting RB placed on IR (ankle) — Wk8",
      "recommendedFaabPct": 18,
      "rosOpponentStrength": "Favorable (2 of next 3 vs bottom-10 run D)"
    }
  ],
  "generatedAt": "2026-07-31T14:02:00Z"
}
```

---

## Error / Empty States (all endpoints)

```json
{ "error": { "code": "PLAYER_NOT_FOUND", "message": "No player found for id 99999." } }
```
```json
{ "error": { "code": "STALE_PROJECTIONS", "message": "No projections generated yet for week 9.", "fallback": "adp_only" } }
```
