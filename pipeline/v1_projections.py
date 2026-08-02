"""
v1 heuristic projection model — populates `projections` and
`defense_matchup_grades` so the app has real floor/median/ceiling/
confidence/recommendation numbers to serve.

This is deliberately NOT docs/03-projection-model-spec.md. That spec calls
for a gradient-boosted usage model (Stage A), a shrinkage-adjusted
efficiency/matchup model (Stage B), quantile regression heads for the
floor/ceiling band, a Vegas market blend (Stage C, needs `player_props` —
empty without ODDS_API_KEY), and SHAP-attributed rationale text. That's a
real modeling project, not something to fake with a few pandas calls.

What this DOES do, honestly:
  - `defense_matchup_grades`: computed from real `player_game_stats` —
    average PPR points a defense has actually allowed to each position
    over the trailing window, ranked 1 (toughest) - 32 (easiest). No
    EPA/play data available from free sources, so `epa_allowed_per_play`
    is left NULL rather than invented.
  - `projections.median_pts`: trailing mean PPR points x a matchup
    multiplier derived from the grade above.
  - `floor_pts` / `ceiling_pts`: mean +/- a multiple of trailing std dev,
    skewed asymmetrically (wider on the ceiling side) to roughly mimic the
    right-skew real quantile regression would capture properly — this is
    a shortcut, not the real thing.
  - `confidence_score`: data sufficiency (games of trailing history),
    score consistency (inverse coefficient of variation), and real
    injury/practice status (25% weight, matching the spec) now that
    ingest_injuries() populates `injuries`. The spec's remaining sub-signal
    (model/market agreement, from the Stage C blend) still isn't
    computable — no market blend exists — so its weight stays folded into
    the other three rather than left out silently.
  - `recommendation`: median_pts vs. a replacement-level baseline. Uses
    the requesting league's actual `roster_settings_json` if one has been
    synced (see espn_ingest.py); otherwise falls back to a standard
    12-team single-flex assumption, clearly logged either way.

Swap this module for a real implementation later without touching the API
layer — it only writes to `projections` (model_version='v1_heuristic') and
`defense_matchup_grades`, the same tables the real pipeline would target.

Run:
  python v1_projections.py --season 2024 --through-week 17 --target-week 18 [--league-id 123456]
"""

import argparse
import os

import psycopg
from psycopg.rows import dict_row

DB_URL = os.environ["DATABASE_URL"]
POSITIONS = ("QB", "RB", "WR", "TE", "K", "DST")

# Standard single-flex 12-team assumption, used only when the target
# league's real roster_settings_json (synced via espn_ingest.py) isn't
# available -- see docstring.
DEFAULT_REPLACEMENT_RANK = {"QB": 13, "RB": 25, "WR": 25, "TE": 13, "K": 13, "DST": 13}

RATIONALE_TREND = {
    "up": "trending up over the last {n} games ({avg:.1f} PPR pts/gm)",
    "down": "trending down over the last {n} games ({avg:.1f} PPR pts/gm)",
    "flat": "averaging {avg:.1f} PPR pts/gm over the last {n} games",
}


def compute_matchup_grades(conn, season, through_week):
    """Real points-allowed-by-position, ranked -- not the EPA-based grade the
    full spec wants (no play-by-play data), but genuinely derived from actual
    outcomes rather than a placeholder."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT
                CASE WHEN s.team_id = g.home_team_id THEN g.away_team_id ELSE g.home_team_id END AS defending_team,
                p.position,
                avg(s.fantasy_pts_ppr) AS pts_allowed_per_game,
                count(*) AS sample_size
            FROM player_game_stats s
            JOIN games g ON g.game_id = s.game_id
            JOIN players p ON p.player_id = s.player_id
            WHERE g.season = %s AND g.week BETWEEN 1 AND %s AND p.position = ANY(%s)
            GROUP BY defending_team, p.position
            """,
            (season, through_week, list(POSITIONS)),
        )
        rows = cur.fetchall()

    by_position = {}
    for r in rows:
        by_position.setdefault(r["position"], []).append(r)

    with conn.cursor() as cur:
        for position, team_rows in by_position.items():
            # Fewest points allowed = toughest matchup = rank 1.
            ranked = sorted(team_rows, key=lambda r: r["pts_allowed_per_game"])
            for i, r in enumerate(ranked, start=1):
                cur.execute(
                    """
                    INSERT INTO defense_matchup_grades
                        (team_id, season, week, vs_position, pts_allowed_per_game, positional_rank)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (team_id, season, week, vs_position) DO UPDATE SET
                        pts_allowed_per_game = EXCLUDED.pts_allowed_per_game,
                        positional_rank = EXCLUDED.positional_rank
                    """,
                    (r["defending_team"], season, through_week, position, round(r["pts_allowed_per_game"], 2), i),
                )
    conn.commit()
    print(f"Matchup grades: {sum(len(v) for v in by_position.values())} team/position rows through week {through_week}")


def fetch_trailing_form(conn, season, through_week, window=5):
    """Last up to `window` games per player through `through_week`, plus
    which team they play in `target_week` isn't known here -- caller resolves
    that separately since it depends on the schedule, not trailing history."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT s.player_id, p.full_name, p.position, p.team_id,
                   array_agg(s.fantasy_pts_ppr ORDER BY g.week DESC) AS recent_scores
            FROM player_game_stats s
            JOIN games g ON g.game_id = s.game_id
            JOIN players p ON p.player_id = s.player_id
            WHERE g.season = %s AND g.week BETWEEN 1 AND %s
              AND p.position = ANY(%s) AND s.fantasy_pts_ppr IS NOT NULL
            GROUP BY s.player_id, p.full_name, p.position, p.team_id
            """,
            (season, through_week, list(POSITIONS)),
        )
        rows = cur.fetchall()
    for r in rows:
        r["recent_scores"] = [float(x) for x in r["recent_scores"][:window]]
    return rows


def resolve_target_week_opponent(conn, season, target_week, team_id):
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT CASE WHEN home_team_id = %s THEN away_team_id ELSE home_team_id END AS opponent
            FROM games
            WHERE season = %s AND week = %s AND (home_team_id = %s OR away_team_id = %s)
            """,
            (team_id, season, target_week, team_id, team_id),
        )
        row = cur.fetchone()
        return row["opponent"] if row else None


def get_matchup_grade(conn, season, through_week, opponent, position):
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT pts_allowed_per_game, positional_rank
            FROM defense_matchup_grades
            WHERE team_id = %s AND season = %s AND week = %s AND vs_position = %s
            """,
            (opponent, season, through_week, position),
        )
        return cur.fetchone()


INJURY_STABILITY = {"Out": 0.0, "Doubtful": 0.15, "Questionable": 0.55}


def get_injury_status(conn, season, week, player_id):
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT game_status, body_part FROM injuries WHERE player_id = %s AND season = %s AND week = %s",
            (player_id, season, week),
        )
        return cur.fetchone()


def position_league_avg(conn, season, through_week, position):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT avg(pts_allowed_per_game) FROM defense_matchup_grades WHERE season=%s AND week=%s AND vs_position=%s",
            (season, through_week, position),
        )
        return cur.fetchone()[0] or 1.0


def get_replacement_ranks(conn, league_id):
    """Uses the real league's roster_settings_json (from a synced ESPN league)
    when available; otherwise the documented 12-team single-flex default."""
    if league_id is None:
        return DEFAULT_REPLACEMENT_RANK, "default 12-team single-flex assumption (no --league-id given)"

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT num_teams, roster_settings_json FROM leagues WHERE league_id = %s", (league_id,))
        row = cur.fetchone()
    if not row or not row["roster_settings_json"]:
        return DEFAULT_REPLACEMENT_RANK, f"league {league_id} not synced yet — falling back to default assumption"

    settings = row["roster_settings_json"]
    num_teams = row["num_teams"] or 12
    flex_pool = settings.get("RB/WR/TE", 0) + settings.get("FLEX", 0)
    ranks = {}
    for pos, settings_key, share in (
        ("QB", "QB", 1.0), ("RB", "RB", 0.4), ("WR", "WR", 0.4), ("TE", "TE", 0.2),
        ("K", "K", 0.0), ("DST", "D/ST", 0.0),  # K/DST never fill flex spots
    ):
        starters = settings.get(settings_key, DEFAULT_REPLACEMENT_RANK[pos] // num_teams)
        ranks[pos] = round(num_teams * (starters + flex_pool * share))
    return ranks, f"derived from league {league_id}'s real roster settings ({num_teams} teams)"


def project(conn, season, through_week, target_week, league_id):
    replacement_ranks, source_note = get_replacement_ranks(conn, league_id)
    print(f"Replacement-level ranks: {replacement_ranks} ({source_note})")

    players = fetch_trailing_form(conn, season, through_week)
    computed = []
    for pl in players:
        scores = pl["recent_scores"]
        n = len(scores)
        if n == 0:
            continue
        mean = sum(scores) / n
        variance = sum((x - mean) ** 2 for x in scores) / n
        std = variance ** 0.5

        opponent = resolve_target_week_opponent(conn, season, target_week, pl["team_id"])
        grade = get_matchup_grade(conn, season, through_week, opponent, pl["position"]) if opponent else None
        league_avg = position_league_avg(conn, season, through_week, pl["position"])

        if grade and league_avg:
            # psycopg returns NUMERIC columns as Decimal -- normalize to float
            # before mixing with the plain-float trailing-stats math below.
            multiplier = max(0.85, min(1.15, float(grade["pts_allowed_per_game"]) / float(league_avg)))
        else:
            multiplier = 1.0  # bye week / unresolved opponent — no matchup signal, don't guess

        median_pts = round(mean * multiplier, 2)
        floor_pts = round(max(0.0, median_pts - 0.9 * std), 2)
        ceiling_pts = round(median_pts + 1.3 * std, 2)

        # Real injury/practice-status signal now that ingest_injuries() is
        # wired up (nflverse_ingest.py) -- weight matches the 25% the spec
        # assigns "injury/practice stability", taken proportionally out of
        # data_sufficiency/consistency rather than left at 0% by default.
        injury = get_injury_status(conn, season, target_week, pl["player_id"])
        injury_stability = INJURY_STABILITY.get(injury["game_status"], 1.0) if injury else 1.0

        data_sufficiency = min(1.0, n / 5)  # 5+ trailing games = fully sufficient
        consistency = 1.0 if mean <= 0 else max(0.0, 1 - min(1.0, std / (mean + 1e-6)))
        confidence = round(100 * (0.40 * data_sufficiency + 0.35 * consistency + 0.25 * injury_stability))
        confidence = max(5, min(95, confidence))

        replacement_rank = replacement_ranks.get(pl["position"])
        computed.append({
            **pl, "opponent": opponent, "grade": grade, "mean": mean, "std": std,
            "median_pts": median_pts, "floor_pts": floor_pts, "ceiling_pts": ceiling_pts,
            "confidence": confidence, "n": n, "injury": injury,
        })

    # Replacement baseline computed within this batch, per position, from the
    # same median_pts values -- rank `replacement_rank` when sorted descending.
    by_position = {}
    for c in computed:
        by_position.setdefault(c["position"], []).append(c)

    baselines = {}
    for position, rows in by_position.items():
        ranked = sorted(rows, key=lambda r: r["median_pts"], reverse=True)
        idx = min(replacement_ranks.get(position, len(ranked)), len(ranked)) - 1
        baselines[position] = ranked[idx]["median_pts"] if ranked else 0.0

    inserted = 0
    with conn.cursor() as cur:
        for c in computed:
            baseline = baselines.get(c["position"], 0.0)
            edge = c["median_pts"] - baseline
            if c["injury"] and c["injury"]["game_status"] == "Out":
                # A trailing-average edge is meaningless if the player is
                # ruled out -- override rather than rely on the confidence
                # threshold alone to catch every case.
                rec = "sit"
            elif edge > 3 and c["confidence"] >= 60:
                rec = "start"
            elif edge < -3 or c["confidence"] < 35:
                rec = "sit"
            else:
                rec = "flex"

            trend_dir = "up" if c["n"] >= 2 and c["recent_scores"][0] > c["mean"] else (
                "down" if c["n"] >= 2 and c["recent_scores"][0] < c["mean"] else "flat"
            )
            trend_phrase = RATIONALE_TREND[trend_dir].format(n=c["n"], avg=c["mean"])
            if c["grade"]:
                matchup_phrase = f"{c['opponent']} ranks {c['grade']['positional_rank']}/32 vs {c['position']}"
            else:
                matchup_phrase = "opponent matchup data unavailable this week"
            rationale = f"{c['full_name']} {trend_phrase}, and {matchup_phrase}."
            if c["injury"] and c["injury"]["game_status"]:
                rationale += f" Listed {c['injury']['game_status']} ({c['injury']['body_part'] or 'undisclosed'})."

            cur.execute(
                """
                INSERT INTO projections
                    (player_id, season, week, model_version, floor_pts, median_pts, ceiling_pts,
                     confidence_score, recommendation, rationale_text)
                VALUES (%s, %s, %s, 'v1_heuristic', %s, %s, %s, %s, %s, %s)
                ON CONFLICT (player_id, season, week, model_version) DO UPDATE SET
                    floor_pts = EXCLUDED.floor_pts,
                    median_pts = EXCLUDED.median_pts,
                    ceiling_pts = EXCLUDED.ceiling_pts,
                    confidence_score = EXCLUDED.confidence_score,
                    recommendation = EXCLUDED.recommendation,
                    rationale_text = EXCLUDED.rationale_text,
                    generated_ts = now()
                """,
                (
                    c["player_id"], season, target_week, c["floor_pts"], c["median_pts"], c["ceiling_pts"],
                    c["confidence"], rec, rationale,
                ),
            )
            inserted += 1
    conn.commit()
    print(f"Projections: {inserted} players projected for season {season} week {target_week}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--through-week", type=int, required=True, help="last week of real data to use as trailing history")
    parser.add_argument("--target-week", type=int, required=True, help="week to generate projections for")
    parser.add_argument("--league-id", type=int, default=None, help="use a synced ESPN league's real roster settings for replacement baseline")
    args = parser.parse_args()

    with psycopg.connect(DB_URL) as conn:
        compute_matchup_grades(conn, args.season, args.through_week)
        project(conn, args.season, args.through_week, args.target_week, args.league_id)
