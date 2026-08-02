"""
GridironIQ backend.

/v1/players/{id}/card, /v1/compare, /v1/draft/tiers, /v1/waivers/candidates,
and /v1/roster from docs/02-api-contracts.md (roster is a later addition,
not in the original contract), implemented against real ingested data
(nflverse stats + the v1_heuristic projections in pipeline/v1_projections.py
— see that file's docstring for what it does and doesn't compute).

/v1/ask is a real LLM call (Claude, via the Anthropic API) grounded in the
same real projection data the other endpoints serve — see that endpoint's
docstring. Everything else in this file is deterministic Python/SQL; this
is the one place the app actually calls a model.

Two real data gaps the contract assumes are filled that aren't yet:
  - `adp` (ADP ingestion was never built — no free source is wired up),
    so /draft/tiers' adp/vona/valueFlag fields are null rather than faked.
  - `news_events` (no ingestion script exists), so nothing here surfaces
    beat-writer/practice-report signals. injuries and depth_charts ARE
    ingested (nflverse_ingest.py) and used in /waivers/candidates and the
    v1 projection model.
"""

import json
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import anthropic
import psycopg
from psycopg.rows import dict_row

app = FastAPI(title="GridironIQ API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # the Vite dev server frontend runs on
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
DB_URL = os.environ["DATABASE_URL"]

# Same assumption pipeline/v1_projections.py falls back to when no real
# league's roster_settings_json has been synced yet.
DEFAULT_REPLACEMENT_RANK = {"QB": 13, "RB": 25, "WR": 25, "TE": 13, "K": 13, "DST": 13}


def get_conn():
    return psycopg.connect(DB_URL, row_factory=dict_row)


@app.get("/health")
def health():
    return {"status": "ok"}


def _player_card_row(conn, player_id, week, season):
    # opponent + matchupRank are real: opponent resolved from the actual
    # schedule, rank from the matchup grades pipeline/v1_projections.py
    # computes from real points-allowed. weather/trend/kpis aren't wired up
    # yet (see module docstring) -- left out of the shape below rather than
    # sent as fake nulls the frontend would render as real "no data" states.
    return conn.execute(
        """
        SELECT p.player_id AS "playerId", p.full_name AS name, p.position, t.team_id AS team,
               pr.floor_pts, pr.median_pts, pr.ceiling_pts,
               pr.confidence_score AS confidence, pr.recommendation, pr.rationale_text AS rationale,
               opp.team_id AS opponent,
               (SELECT dmg.positional_rank FROM defense_matchup_grades dmg
                 WHERE dmg.team_id = opp.team_id AND dmg.season = %(season)s
                   AND dmg.vs_position = p.position AND dmg.week <= %(week)s
                 ORDER BY dmg.week DESC LIMIT 1) AS "matchupRank"
        FROM players p
        JOIN teams t ON t.team_id = p.team_id
        LEFT JOIN projections pr
          ON pr.player_id = p.player_id AND pr.week = %(week)s AND pr.season = %(season)s
        LEFT JOIN games g
          ON g.season = %(season)s AND g.week = %(week)s
         AND (g.home_team_id = p.team_id OR g.away_team_id = p.team_id)
        LEFT JOIN teams opp
          ON opp.team_id = CASE WHEN g.home_team_id = p.team_id THEN g.away_team_id ELSE g.home_team_id END
        WHERE p.player_id = %(player_id)s
        """,
        {"season": season, "week": week, "player_id": player_id},
    ).fetchone()


def _shape_card(row):
    if not row:
        return None
    matchup = None
    if row["opponent"] and row["matchupRank"] is not None:
        matchup = {"vsPositionRank": row["matchupRank"], "note": f"{row['opponent']} ranks {row['matchupRank']}/32 vs {row['position']}"}
    return {
        "playerId": row["playerId"], "name": row["name"], "position": row["position"],
        "team": row["team"], "opponent": row["opponent"],
        "recommendation": row["recommendation"], "confidence": row["confidence"],
        "projection": {"floor": row["floor_pts"], "median": row["median_pts"], "ceiling": row["ceiling_pts"]},
        "matchup": matchup,
        "rationale": row["rationale"],
    }


@app.get("/v1/players/{player_id}/card")
def player_card(player_id: str, week: int, season: int, scoring: str = "ppr"):
    with get_conn() as conn:
        row = _player_card_row(conn, player_id, week, season)
    if not row:
        return {"error": {"code": "PLAYER_NOT_FOUND"}}
    return _shape_card(row)


@app.get("/v1/compare")
def compare(playerIds: str, week: int, season: int, scoring: str = "ppr"):
    ids = playerIds.split(",")
    if len(ids) != 2:
        return {"error": {"code": "INVALID_REQUEST", "message": "playerIds must contain exactly 2 ids"}}

    with get_conn() as conn:
        rows = [_player_card_row(conn, pid, week, season) for pid in ids]
    if any(r is None for r in rows):
        return {"error": {"code": "PLAYER_NOT_FOUND"}}

    cards = [_shape_card(r) for r in rows]
    a, b = cards

    # confidence_score measures trust in a projection, not play quality --
    # ranking on it directly (the original version of this endpoint) could
    # recommend a confidently-flagged FLEX/SIT play over a less-certain but
    # clearly better START, which is backwards. Rank by recommendation tier
    # first, median_pts as the tiebreaker within a tier; confidenceGap is
    # still reported since it's part of the documented response shape, but
    # it no longer decides the winner.
    REC_TIER = {"start": 2, "flex": 1, "sit": 0}
    def rank(c):
        return (REC_TIER.get(c["recommendation"], -1), c["projection"]["median"] or 0)

    winner, loser = (a, b) if rank(a) >= rank(b) else (b, a)
    gap = (winner["confidence"] or 0) - (loser["confidence"] or 0)
    return {
        "players": cards,
        "edge": {
            "winnerId": winner["playerId"],
            "confidenceGap": gap,
            "summary": f"Start {winner['name']} over {loser['name']} — {winner['projection']['median']} vs {loser['projection']['median']} projected pts",
        },
    }


def _replacement_rank(conn, position, league_id):
    """Same logic as pipeline/v1_projections.py's get_replacement_ranks, kept
    as a small duplicate here rather than a shared import since backend/ and
    pipeline/ ship in separate containers -- if this needs a third copy,
    factor it into a shared package instead of copying again."""
    if league_id is None:
        return DEFAULT_REPLACEMENT_RANK.get(position, 25)
    row = conn.execute(
        "SELECT num_teams, roster_settings_json FROM leagues WHERE league_id = %s", (league_id,)
    ).fetchone()
    if not row or not row["roster_settings_json"]:
        return DEFAULT_REPLACEMENT_RANK.get(position, 25)
    settings, num_teams = row["roster_settings_json"], row["num_teams"] or 12
    flex_pool = settings.get("RB/WR/TE", 0) + settings.get("FLEX", 0)
    share = {"QB": 1.0, "RB": 0.4, "WR": 0.4, "TE": 0.2}.get(position, 0)  # K/DST never fill flex spots
    settings_key = {"DST": "D/ST"}.get(position, position)
    starters = settings.get(settings_key, DEFAULT_REPLACEMENT_RANK.get(position, 25) // num_teams)
    return round(num_teams * (starters + flex_pool * share))


def _team_implied_totals(conn, season):
    """Real Vegas-derived team strength signal: average implied points per
    game across the season's currently-posted lines (odds_ingest.py). Not
    a projection input yet (the v1 model doesn't use it) -- this is
    specifically for draft context, where the whole season's offensive
    environment matters more than any single week's matchup.
    """
    rows = conn.execute(
        """
        SELECT team, avg(implied_total) AS avg_implied FROM (
            SELECT g.home_team_id AS team, v.home_implied_total AS implied_total
            FROM vegas_lines v JOIN games g ON g.game_id = v.game_id WHERE g.season = %(season)s
            UNION ALL
            SELECT g.away_team_id AS team, v.away_implied_total AS implied_total
            FROM vegas_lines v JOIN games g ON g.game_id = v.game_id WHERE g.season = %(season)s
        ) x
        WHERE implied_total IS NOT NULL
        GROUP BY team
        """,
        {"season": season},
    ).fetchall()
    ranked = sorted(rows, key=lambda r: r["avg_implied"], reverse=True)
    return {r["team"]: {"avgImplied": round(float(r["avg_implied"]), 1), "rank": i + 1} for i, r in enumerate(ranked)}


@app.get("/v1/team-environments")
def team_environments(season: int):
    """Not in docs/02-api-contracts.md -- added once odds_ingest.py had real
    2026 season-long lines to compute this from. Powers the Draft Strategy
    panel's best/worst offensive environment callout."""
    with get_conn() as conn:
        totals = _team_implied_totals(conn, season)
    ranked = sorted(totals.items(), key=lambda kv: kv[1]["rank"])
    return {"season": season, "teams": [{"team": t, **v} for t, v in ranked]}


@app.get("/v1/draft/tiers")
def draft_tiers(position: str, season: int, week: int, scoring: str = "ppr", leagueId: int | None = None):
    with get_conn() as conn:
        positions = ["QB", "RB", "WR", "TE"] if position == "ALL" else [position]
        rows = conn.execute(
            """
            SELECT p.player_id, p.full_name AS name, p.position, p.team_id AS team, pr.median_pts
            FROM projections pr
            JOIN players p ON p.player_id = pr.player_id
            WHERE pr.season = %s AND pr.week = %s AND p.position = ANY(%s) AND pr.median_pts IS NOT NULL
            ORDER BY pr.median_pts DESC
            """,
            (season, week, positions),
        ).fetchall()

        if not rows:
            return {"position": position, "tiers": [], "error": {"code": "STALE_PROJECTIONS",
                     "message": f"No projections generated yet for week {week}.", "fallback": "adp_only"}}

        replacement_rank = _replacement_rank(conn, position, leagueId)
        # Real signal from real 2026-season Vegas lines -- projections are
        # season=2025 (most recent real player-stats data), but Vegas lines
        # are naturally forward-looking, so this deliberately looks at the
        # upcoming 2026 season regardless of which season `season` param is.
        team_environments = _team_implied_totals(conn, 2026)

    baseline = rows[min(replacement_rank, len(rows)) - 1]["median_pts"] if position != "ALL" else 0

    # Gap-based tiering: start a new tier whenever the drop to the next
    # player exceeds 15% of the current tier's value -- a cheap stand-in for
    # the real k-means/std-dev clustering the spec calls for, but genuinely
    # data-driven rather than fixed rank cutoffs.
    tiers, current_tier, tier_num = [], [], 1
    for i, r in enumerate(rows):
        if current_tier:
            prev = current_tier[-1]["projectedPts"]
            if prev > 0 and (prev - r["median_pts"]) / prev > 0.15:
                tiers.append((tier_num, current_tier))
                current_tier, tier_num = [], tier_num + 1
        env = team_environments.get(r["team"])
        current_tier.append({
            "playerId": r["player_id"], "name": r["name"], "team": r["team"], "position": r["position"],
            "adp": None, "vbd": round(float(r["median_pts"]) - float(baseline), 1) if position != "ALL" else None,
            "vona": None, "projectedPts": r["median_pts"], "valueFlag": None,
            "teamImpliedTotal": env["avgImplied"] if env else None,
            "teamImpliedRank": env["rank"] if env else None,
        })
    if current_tier:
        tiers.append((tier_num, current_tier))

    return {
        "position": position,
        "tiers": [{"tier": n, "label": f"Tier {n}", "players": players} for n, players in tiers],
    }


@app.get("/v1/waivers/candidates")
def waiver_candidates(season: int, week: int, position: str | None = None, leagueId: int | None = None):
    with get_conn() as conn:
        position_filter = [position] if position else ["QB", "RB", "WR", "TE"]
        rows = conn.execute(
            """
            SELECT s.player_id, p.full_name AS name, p.position, p.team_id AS team,
                   array_agg(s.snap_pct ORDER BY g.week DESC) FILTER (WHERE s.snap_pct IS NOT NULL) AS snaps,
                   array_agg(s.fantasy_pts_ppr ORDER BY g.week DESC) AS pts
            FROM player_game_stats s
            JOIN games g ON g.game_id = s.game_id
            JOIN players p ON p.player_id = s.player_id
            WHERE g.season = %s AND g.week <= %s AND p.position = ANY(%s)
            GROUP BY s.player_id, p.full_name, p.position, p.team_id
            HAVING count(*) >= 2
            """,
            (season, week, position_filter),
        ).fetchall()

        # A "waiver candidate" who's already on a roster in this league isn't
        # a real candidate -- the original version of this endpoint never
        # checked, which is a correctness bug now that we can actually check.
        rostered_ids = set()
        rostered_pct = {}
        if leagueId is not None:
            rostered_ids = {
                r["player_id"] for r in conn.execute(
                    "SELECT player_id FROM roster_slots WHERE league_id = %s AND dropped_ts IS NULL", (leagueId,)
                ).fetchall()
            }
            rostered_pct = {
                r["player_id"]: float(r["percent_owned"]) for r in conn.execute(
                    "SELECT player_id, percent_owned FROM league_free_agents WHERE league_id = %s", (leagueId,)
                ).fetchall() if r["percent_owned"] is not None
            }

        # Real vacancy detection: a depth chart teammate ranked ahead of this
        # player who's Out/Doubtful this week is a genuine opportunity signal
        # -- not a guess, computed from actual depth_charts + injuries.
        depth_rows = conn.execute(
            "SELECT team_id, position, player_id, depth_rank FROM depth_charts WHERE season = %s AND week = %s",
            (season, week),
        ).fetchall()
        depth_by_team_pos = {}
        for d in depth_rows:
            depth_by_team_pos.setdefault((d["team_id"], d["position"]), []).append(d)
        player_depth = {d["player_id"]: d for d in depth_rows}
        injured = {
            r["player_id"]: r["game_status"] for r in conn.execute(
                "SELECT player_id, game_status FROM injuries WHERE season = %s AND week = %s AND game_status IN ('Out','Doubtful')",
                (season, week),
            ).fetchall()
        }
        player_names = {p["player_id"]: p["name"] for p in conn.execute("SELECT player_id, full_name AS name FROM players").fetchall()}

    candidates = []
    for r in rows:
        if r["player_id"] in rostered_ids:
            continue
        snaps = [float(x) for x in (r["snaps"] or [])][:5]
        pts = [float(x) for x in (r["pts"] or [])][:5]
        if len(snaps) < 2:
            continue
        recent, prior = snaps[0], sum(snaps[1:]) / len(snaps[1:])
        # Real, if simple: reward both current usage level and an upward
        # trend in snap share. Coefficients tuned so a real starter-level
        # snap share with a real upward trend lands well below 100, not at
        # the ceiling -- the original weights saturated almost every Week-18
        # backup (many teams rest starters in a meaningless finale, so a
        # jump from 5% to 40% snaps reads as a huge "trend" despite meaning
        # little).
        breakout_score = round(max(0, min(100, recent * 45 + max(0, recent - prior) * 90)))

        vacancy_reason = None
        my_depth = player_depth.get(r["player_id"])
        if my_depth:
            ahead = [d for d in depth_by_team_pos.get((my_depth["team_id"], my_depth["position"]), [])
                     if d["depth_rank"] < my_depth["depth_rank"] and d["player_id"] in injured]
            if ahead:
                blocker = ahead[0]
                vacancy_reason = f"{player_names.get(blocker['player_id'], 'Depth chart starter')} listed {injured[blocker['player_id']]}"

        candidates.append({
            "playerId": r["player_id"], "name": r["name"], "position": r["position"], "team": r["team"],
            "rosteredPct": rostered_pct.get(r["player_id"]),
            "trend": {"metric": "snapPct", "points": list(reversed(snaps))},
            "breakoutScore": breakout_score,
            "vacancyReason": vacancy_reason,
            "recommendedFaabPct": round(breakout_score / 5),
        })

    candidates.sort(key=lambda c: c["breakoutScore"], reverse=True)
    return {"week": week, "candidates": candidates[:25]}


@app.get("/v1/roster")
def roster(leagueId: int, teamName: str, season: int, week: int):
    """Not in docs/02-api-contracts.md -- added once espn_ingest.py made a
    real synced roster available. Powers the Home screen's actual lineup
    view and the draft strategy position-count tracker."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT p.player_id AS "playerId", p.full_name AS name, p.position, p.team_id AS team,
                   rs.slot_type AS "slotType", pr.median_pts, pr.confidence_score AS confidence,
                   pr.recommendation
            FROM roster_slots rs
            JOIN players p ON p.player_id = rs.player_id
            JOIN league_members lm ON lm.league_id = rs.league_id AND lm.user_id = rs.user_id
            LEFT JOIN projections pr ON pr.player_id = p.player_id AND pr.season = %(season)s AND pr.week = %(week)s
            WHERE rs.league_id = %(leagueId)s AND lm.team_name ILIKE %(teamName)s AND rs.dropped_ts IS NULL
            ORDER BY p.position, pr.median_pts DESC NULLS LAST
            """,
            {"leagueId": leagueId, "teamName": f"%{teamName}%", "season": season, "week": week},
        ).fetchall()

    if not rows:
        return {"error": {"code": "ROSTER_NOT_FOUND", "message": f"No synced roster for team matching '{teamName}' in league {leagueId}."}}

    position_counts = {}
    for r in rows:
        position_counts[r["position"]] = position_counts.get(r["position"], 0) + 1

    return {"leagueId": leagueId, "teamName": teamName, "players": rows, "positionCounts": position_counts}


ASK_SYSTEM_PROMPT = """You are the in-app assistant for GridironIQ, a fantasy football decision-support app.

You will be given real player projection data as JSON (floor/median/ceiling points, confidence score, matchup rank, recommendation, and rationale — all computed by the app's own model, not by you) and a user question about it. Answer using only the numbers you were given; do not invent stats, injury news, or matchup details not present in the JSON. If the data needed to answer isn't in the context, say so plainly rather than guessing.

Keep answers short — a few sentences, not a report. Do not include any internal reasoning tags or meta-commentary in your response, only the answer itself."""


class AskRequest(BaseModel):
    question: str
    playerIds: list[str] = []
    season: int
    week: int


@app.post("/v1/ask")
def ask(req: AskRequest):
    """Real LLM call (Claude via the Anthropic API), grounded in the same
    real projection data /v1/compare and /v1/players/{id}/card serve --
    this does NOT invent stats, it answers from the JSON context below.
    Requires ANTHROPIC_API_KEY. Uses low effort + thinking disabled since
    this is a simple grounded Q&A over numbers already computed elsewhere,
    not a task that needs deep reasoning -- keeps latency and cost down.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        # An empty/missing key raises a TypeError deep in the SDK's request
        # builder, not AuthenticationError -- that only fires for a key the
        # API itself rejects. Check upfront for a clean error either way.
        return {"error": {"code": "MISSING_API_KEY", "message": "ANTHROPIC_API_KEY is not set on the backend."}}

    with get_conn() as conn:
        rows = [_player_card_row(conn, pid, req.week, req.season) for pid in req.playerIds]
    cards = [_shape_card(r) for r in rows if r]

    context = json.dumps({"players": cards}, default=str)

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
    try:
        response = client.messages.create(
            model="claude-opus-5",
            max_tokens=1024,
            thinking={"type": "disabled"},
            output_config={"effort": "low"},
            system=ASK_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": f"Real player data (JSON):\n{context}\n\nQuestion: {req.question}",
            }],
        )
    except anthropic.AuthenticationError:
        return {"error": {"code": "MISSING_API_KEY", "message": "ANTHROPIC_API_KEY is not set or invalid on the backend."}}

    if response.stop_reason == "refusal":
        return {"error": {"code": "REFUSED", "message": "The model declined to answer this question."}}

    answer = next((b.text for b in response.content if b.type == "text"), "")
    return {"answer": answer, "playersInContext": [c["name"] for c in cards]}
