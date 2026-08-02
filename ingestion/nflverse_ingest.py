"""
Ingest teams, games, players, weekly stats, and snap counts from nflverse
(free, public, via nfl_data_py) into the schema's natural-key tables.

IDs used directly, no crosswalk needed for this source:
  - teams.team_id       = nflverse team abbreviation ('KC', 'BUF', ...)
  - players.player_id   = nflverse gsis_id ('00-0034796')
  - games.game_id       = nflverse game_id ('{season}_{week:02d}_{away}_{home}')

Run: python nflverse_ingest.py --season 2026 --week 9
"""

import argparse
import hashlib
import os
import pandas as pd
import psycopg
import nfl_data_py as nfl

DB_URL = os.environ["DATABASE_URL"]


def _stable_id(*parts):
    """Deterministic positive bigint from a natural key (injuries has no
    numeric id of its own) -- same approach as espn_ingest.py's stable_id,
    so re-running ingestion updates rows instead of duplicating them."""
    digest = hashlib.sha256(":".join(str(p) for p in parts).encode()).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFFFFFFFFFFFFFF


def ingest_teams(conn):
    teams_df = nfl.import_team_desc()
    with conn.cursor() as cur:
        for _, row in teams_df.iterrows():
            cur.execute(
                """
                INSERT INTO teams (team_id, city, name, conference, division)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (team_id) DO UPDATE SET
                    city = EXCLUDED.city, name = EXCLUDED.name
                """,
                (
                    row["team_abbr"],
                    row.get("team_name", "").rsplit(" ", 1)[0],
                    row.get("team_name", ""),
                    row.get("team_conf", ""),
                    row.get("team_division", ""),
                ),
            )
    conn.commit()


def ingest_games(conn, season):
    """Populates `games` from the official schedule — needed before weekly
    stats/odds/weather can resolve a real game_id."""
    sched_df = nfl.import_schedules([season])
    with conn.cursor() as cur:
        for _, g in sched_df.iterrows():
            cur.execute(
                """
                INSERT INTO games (game_id, season, week, home_team_id, away_team_id, kickoff_ts, game_status)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (game_id) DO UPDATE SET game_status = EXCLUDED.game_status
                """,
                (
                    g["game_id"],
                    season,
                    g["week"],
                    g["home_team"],
                    g["away_team"],
                    g.get("gameday_datetime") or g.get("gameday"),
                    "final" if g.get("result") is not None else "scheduled",
                ),
            )
    conn.commit()
    print(f"Ingested {len(sched_df)} games for {season}")


def ingest_players(conn, season):
    roster_df = nfl.import_seasonal_rosters([season])
    with conn.cursor() as cur:
        for _, row in roster_df.iterrows():
            if row.get("position") not in ("QB", "RB", "WR", "TE", "K"):
                continue
            # This nfl_data_py version names the gsis-format id "player_id" in
            # import_seasonal_rosters()'s output (not "gsis_id" as the column
            # is called in other nflverse tables) -- confirmed against a live
            # pull, e.g. Aaron Rodgers -> '00-0023459'.
            if not row.get("player_id"):
                continue
            cur.execute(
                """
                INSERT INTO players (player_id, full_name, position, team_id, jersey_number, status)
                VALUES (%s, %s, %s, %s, %s, 'active')
                ON CONFLICT (player_id) DO UPDATE SET
                    full_name = EXCLUDED.full_name,
                    position = EXCLUDED.position,
                    team_id = EXCLUDED.team_id,
                    jersey_number = EXCLUDED.jersey_number,
                    updated_at = now()
                """,
                (
                    row["player_id"],
                    row.get("player_name"),
                    row.get("position"),
                    row.get("team"),
                    # jersey_number is a pandas float column; NaN (missing)
                    # can't cast into Postgres smallint ("smallint out of
                    # range"), unlike the NUMERIC columns elsewhere that
                    # tolerate NaN fine -- coerce to None explicitly.
                    None if pd.isna(row.get("jersey_number")) else int(row["jersey_number"]),
                ),
            )
    conn.commit()


def _resolve_game_id(sched_df, season, week, team_abbr):
    match = sched_df[
        (sched_df["season"] == season) & (sched_df["week"] == week)
        & ((sched_df["home_team"] == team_abbr) | (sched_df["away_team"] == team_abbr))
    ]
    return match.iloc[0]["game_id"] if len(match) else None


def _kicker_fantasy_points(r):
    """nflverse's precomputed fantasy_points(_ppr) columns don't include
    kicking at all -- verified live: real kickers who hit 4/6 FGs still show
    ~0 in that column. Compute standard kicker scoring manually from the
    real made/missed counts instead. This is common ESPN-default kicker
    scoring (FG value scales with distance, PAT flat, misses penalized) --
    not necessarily this league's exact settings, since kicker scoring
    rules aren't captured in league.roster_settings_json."""
    made_pts = (
        (r.get("fg_made_0_19") or 0) * 3 + (r.get("fg_made_20_29") or 0) * 3
        + (r.get("fg_made_30_39") or 0) * 3 + (r.get("fg_made_40_49") or 0) * 4
        + (r.get("fg_made_50_59") or 0) * 5 + (r.get("fg_made_60_") or 0) * 5
        + (r.get("pat_made") or 0) * 1
    )
    missed_pts = ((r.get("fg_missed") or 0) + (r.get("pat_missed") or 0)) * -1
    return round(made_pts + missed_pts, 2)


def ingest_weekly_stats(conn, season, week):
    """nfl_data_py 0.3.3's import_weekly_data() points at nflverse's OLD
    "player_stats" release, which nflverse stopped updating after the 2024
    season -- confirmed by checking the release directly (no 2025 asset
    exists there). nflverse migrated real per-week stats to a renamed
    release, "stats_player" (asset stats_player_week_{season}.parquet),
    which nfl_data_py hasn't caught up to. Pull it directly instead of
    going through the stale wrapper function. Bonus: this source includes
    a real `game_id` per row in our exact format, so no schedule-matching
    is needed the way the old source required.
    """
    url = f"https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{season}.parquet"
    weekly_df = pd.read_parquet(url)
    weekly_df = weekly_df[(weekly_df["week"] == week) & (weekly_df["season_type"] == "REG")]

    # Same gap as the old source: this includes players outside
    # import_seasonal_rosters()'s pool (practice-squad, etc.) -- skip them
    # rather than let the FK violation crash the whole ingest run.
    with conn.cursor() as cur:
        cur.execute("SELECT player_id FROM players")
        known_player_ids = {row[0] for row in cur.fetchall()}

    inserted, skipped = 0, 0
    with conn.cursor() as cur:
        for _, r in weekly_df.iterrows():
            game_id = r.get("game_id")
            if not game_id or not r.get("player_id") or r.get("player_id") not in known_player_ids:
                skipped += 1
                continue
            cur.execute(
                """
                INSERT INTO player_game_stats (
                    player_id, game_id, team_id,
                    completions, pass_attempts, pass_yards, pass_tds, interceptions,
                    epa_per_dropback, cpoe,
                    carries, rush_yards, rush_tds,
                    targets, receptions, rec_yards, rec_tds, air_yards, adot,
                    target_share, air_yards_share, wopr, yards_after_catch,
                    fantasy_pts_ppr
                ) VALUES (
                    %(player_id)s, %(game_id)s, %(team_id)s,
                    %(completions)s, %(attempts)s, %(passing_yards)s, %(passing_tds)s, %(interceptions)s,
                    %(passing_epa)s, %(cpoe)s,
                    %(carries)s, %(rushing_yards)s, %(rushing_tds)s,
                    %(targets)s, %(receptions)s, %(receiving_yards)s, %(receiving_tds)s,
                    %(receiving_air_yards)s, %(adot)s,
                    %(target_share)s, %(air_yards_share)s, %(wopr)s, %(receiving_yards_after_catch)s,
                    %(fantasy_points_ppr)s
                )
                ON CONFLICT (player_id, game_id) DO UPDATE SET
                    fantasy_pts_ppr = EXCLUDED.fantasy_pts_ppr,
                    target_share = EXCLUDED.target_share,
                    wopr = EXCLUDED.wopr
                """,
                {
                    "player_id": r["player_id"],
                    "game_id": game_id,
                    "team_id": r.get("team"),
                    "completions": r.get("completions"),
                    "attempts": r.get("attempts"),
                    "passing_yards": r.get("passing_yards"),
                    "passing_tds": r.get("passing_tds"),
                    "interceptions": r.get("passing_interceptions"),
                    "passing_epa": r.get("passing_epa"),
                    "cpoe": r.get("passing_cpoe"),
                    "carries": r.get("carries"),
                    "rushing_yards": r.get("rushing_yards"),
                    "rushing_tds": r.get("rushing_tds"),
                    "targets": r.get("targets"),
                    "receptions": r.get("receptions"),
                    "receiving_yards": r.get("receiving_yards"),
                    "receiving_tds": r.get("receiving_tds"),
                    "receiving_air_yards": r.get("receiving_air_yards"),
                    "adot": (r.get("receiving_air_yards") / r["targets"]) if r.get("targets") else None,
                    "target_share": r.get("target_share"),
                    "air_yards_share": r.get("air_yards_share"),
                    "wopr": r.get("wopr"),
                    "receiving_yards_after_catch": r.get("receiving_yards_after_catch"),
                    "fantasy_points_ppr": _kicker_fantasy_points(r) if r.get("position") == "K" else r.get("fantasy_points_ppr"),
                },
            )
            inserted += 1
    conn.commit()
    print(f"Weekly stats: inserted/updated {inserted}, skipped {skipped} (no game_id match) for {season} wk{week}")


PRACTICE_STATUS_CODE = {
    "Did Not Participate In Practice": "DNP",
    "Limited Participation in Practice": "Limited",
    "Full Participation in Practice": "Full",
}


def ingest_injuries(conn, season, week):
    """import_injuries() gives one row per player per week with the latest
    practice/game status -- nflverse doesn't break this out by Wed/Thu/Fri
    the way our schema's practice_status_wed/thu/fri columns anticipate, so
    only practice_status_fri (the final, most game-relevant estimate) is
    populated; wed/thu stay NULL rather than duplicating the same value into
    all three and implying we tracked something we didn't.

    Raw practice_status values are full sentences ("Did Not Participate In
    Practice") that don't fit practice_status_fri's VARCHAR(20) -- the
    column's own comment ("DNP, Limited, Full") makes clear short codes were
    intended, so normalize rather than widen the column for free text.
    """
    inj_df = nfl.import_injuries([season])
    inj_df = inj_df[inj_df["week"] == week]

    with conn.cursor() as cur:
        cur.execute("SELECT player_id FROM players")
        known_player_ids = {row[0] for row in cur.fetchall()}

    stored, skipped = 0, 0
    with conn.cursor() as cur:
        for _, r in inj_df.iterrows():
            if not r.get("gsis_id") or r["gsis_id"] not in known_player_ids:
                skipped += 1
                continue
            injury_id = _stable_id("injury", r["gsis_id"], season, week)
            cur.execute(
                """
                INSERT INTO injuries (injury_id, player_id, season, week, body_part,
                                       practice_status_fri, game_status, reported_ts)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (injury_id) DO UPDATE SET
                    body_part = EXCLUDED.body_part,
                    practice_status_fri = EXCLUDED.practice_status_fri,
                    game_status = EXCLUDED.game_status,
                    reported_ts = EXCLUDED.reported_ts
                """,
                (
                    injury_id, r["gsis_id"], season, week,
                    r.get("report_primary_injury"),
                    PRACTICE_STATUS_CODE.get(r.get("practice_status")),
                    r.get("report_status") if r.get("report_status") != "Note" else None,
                    r.get("date_modified"),
                ),
            )
            stored += 1
    conn.commit()
    print(f"Injuries: stored {stored}, skipped {skipped} (player not in `players`) for {season} wk{week}")


def ingest_depth_charts(conn, season, week):
    """Offense only, skill positions only -- our `players` table (via
    ingest_players) only has QB/RB/WR/TE, so OL/DL/DB depth chart rows would
    never resolve to a real player_id anyway.

    nflverse changed this source's shape at some point after 2024: for 2025+
    it's a single dated snapshot (a `dt` timestamp, no `season`/`week`/
    `formation` columns) rather than a per-week historical series -- real
    upstream change, not a bug here. Detect it and skip cleanly rather than
    force a bad fit; depth-chart-based waiver vacancy detection just returns
    null for these weeks instead of crashing the whole ingest run.
    """
    dc_df = nfl.import_depth_charts([season])
    if "week" not in dc_df.columns:
        print(f"Depth charts: source for {season} is a snapshot format (no week column) -- skipping wk{week}")
        return
    dc_df = dc_df[(dc_df["week"] == week) & (dc_df["formation"] == "Offense")
                  & (dc_df["position"].isin(["QB", "RB", "WR", "TE"]))]

    with conn.cursor() as cur:
        cur.execute("SELECT player_id FROM players")
        known_player_ids = {row[0] for row in cur.fetchall()}

    stored, skipped = 0, 0
    with conn.cursor() as cur:
        for _, r in dc_df.iterrows():
            if not r.get("gsis_id") or r["gsis_id"] not in known_player_ids:
                skipped += 1
                continue
            try:
                depth_rank = int(r["depth_team"])
            except (TypeError, ValueError):
                skipped += 1
                continue
            cur.execute(
                """
                INSERT INTO depth_charts (team_id, season, week, position, player_id, depth_rank)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (team_id, season, week, position, depth_rank) DO UPDATE SET
                    player_id = EXCLUDED.player_id
                """,
                (r["club_code"], season, week, r["position"], r["gsis_id"], depth_rank),
            )
            stored += 1
    conn.commit()
    print(f"Depth charts: stored {stored}, skipped {skipped} for {season} wk{week}")


def ingest_snap_counts(conn, season, week):
    """
    Snap counts come keyed by pfr_id, not gsis_id — bridge via nfl_data_py's
    id crosswalk. NOTE: this gives overall snap_pct, not true route
    participation (routes run isn't in any free nflverse release — that's
    PFF/paid-tier data). snap_pct is used as the closest free proxy;
    route_participation_pct is intentionally left NULL rather than faked.
    """
    snaps_df = nfl.import_snap_counts([season])
    snaps_df = snaps_df[snaps_df["week"] == week]
    id_map = nfl.import_ids()[["gsis_id", "pfr_id"]].dropna()
    pfr_to_gsis = dict(zip(id_map["pfr_id"], id_map["gsis_id"]))
    sched_df = nfl.import_schedules([season])

    updated = 0
    with conn.cursor() as cur:
        for _, r in snaps_df.iterrows():
            gsis_id = pfr_to_gsis.get(r.get("pfr_player_id"))
            game_id = _resolve_game_id(sched_df, season, week, r.get("team"))
            if not gsis_id or not game_id:
                continue
            cur.execute(
                """
                UPDATE player_game_stats
                SET snaps_played = %s, snap_pct = %s
                WHERE player_id = %s AND game_id = %s
                """,
                (r.get("offense_snaps"), r.get("offense_pct"), gsis_id, game_id),
            )
            updated += cur.rowcount
    conn.commit()
    print(f"Snap counts: updated {updated} rows for {season} wk{week} (route_participation_pct not available free)")


def _dst_player_id(team_id):
    return f"{team_id}_DST"


def ingest_dst_players(conn):
    """DST isn't a real nflverse player -- it's fantasy-specific, scored at
    the team level. Create one synthetic players row per team (player_id =
    '{team}_DST', position='DST') so team defense fits into the existing
    players/player_game_stats/projections pipeline without a parallel schema.
    One-time/idempotent -- safe to re-run."""
    teams = conn.execute("SELECT team_id, name FROM teams").fetchall()
    with conn.cursor() as cur:
        for team_id, name in teams:
            cur.execute(
                """
                INSERT INTO players (player_id, full_name, position, team_id, status)
                VALUES (%s, %s, 'DST', %s, 'active')
                ON CONFLICT (player_id) DO UPDATE SET full_name = EXCLUDED.full_name, updated_at = now()
                """,
                (_dst_player_id(team_id), f"{name} D/ST", team_id),
            )
    conn.commit()
    print(f"DST players: {len(teams)} team-defense rows ensured")


# Standard DST scoring. Built from real defensive stats (stats_team_week)
# and real final scores (schedules) -- not every DST scoring wrinkle is
# covered: blocked kicks aren't included (nflverse's fg_blocked/pt_blocked
# columns are from the KICKING team's side, not credited to the blocking
# defense, and cross-referencing that correctly was more scope than this
# warranted), and TD-scoring columns (def_tds, special_teams_tds,
# fumble_recovery_tds) are summed as given rather than manually
# deduplicated against each other -- if nflverse's own categories overlap,
# this could double-count a return TD. Everything else (sacks,
# interceptions, fumble recoveries, safeties, points-allowed tiers) is
# exact.
POINTS_ALLOWED_TIERS = [(0, 10), (6, 7), (13, 4), (20, 1), (27, 0), (34, -1), (999, -4)]


def _points_allowed_bonus(points):
    for threshold, bonus in POINTS_ALLOWED_TIERS:
        if points <= threshold:
            return bonus
    return -4


def ingest_dst_weekly_stats(conn, season, week):
    team_df = pd.read_parquet(f"https://github.com/nflverse/nflverse-data/releases/download/stats_team/stats_team_week_{season}.parquet")
    team_df = team_df[(team_df["week"] == week) & (team_df["season_type"] == "REG")]
    sched_df = nfl.import_schedules([season])
    sched_wk = sched_df[sched_df["week"] == week]

    stored, skipped = 0, 0
    with conn.cursor() as cur:
        for _, r in team_df.iterrows():
            team = r["team"]
            game_id = _resolve_game_id(sched_df, season, week, team)
            game_row = sched_wk[(sched_wk["home_team"] == team) | (sched_wk["away_team"] == team)]
            if not game_id or game_row.empty:
                skipped += 1
                continue
            g = game_row.iloc[0]
            points_allowed = g["away_score"] if g["home_team"] == team else g["home_score"]
            if pd.isna(points_allowed):
                skipped += 1  # game not yet played -- no real result to score against
                continue

            fantasy_pts = (
                (r.get("def_sacks") or 0) * 1
                + (r.get("def_interceptions") or 0) * 2
                + (r.get("fumble_recovery_opp") or 0) * 2
                + (r.get("def_safeties") or 0) * 2
                + ((r.get("def_tds") or 0) + (r.get("special_teams_tds") or 0) + (r.get("fumble_recovery_tds") or 0)) * 6
                + _points_allowed_bonus(points_allowed)
            )

            cur.execute(
                """
                INSERT INTO player_game_stats (player_id, game_id, team_id, fantasy_pts_ppr)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (player_id, game_id) DO UPDATE SET fantasy_pts_ppr = EXCLUDED.fantasy_pts_ppr
                """,
                (_dst_player_id(team), game_id, team, round(fantasy_pts, 2)),
            )
            stored += 1
    conn.commit()
    print(f"DST weekly stats: stored {stored}, skipped {skipped} (no game/result) for {season} wk{week}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    args = parser.parse_args()

    with psycopg.connect(DB_URL) as conn:
        ingest_teams(conn)
        ingest_games(conn, args.season)
        ingest_players(conn, args.season)
        ingest_dst_players(conn)
        ingest_weekly_stats(conn, args.season, args.week)
        ingest_dst_weekly_stats(conn, args.season, args.week)
        ingest_snap_counts(conn, args.season, args.week)
        ingest_injuries(conn, args.season, args.week)
        ingest_depth_charts(conn, args.season, args.week)
