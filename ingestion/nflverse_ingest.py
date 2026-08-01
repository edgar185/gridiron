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
import os
import psycopg
import nfl_data_py as nfl

DB_URL = os.environ["DATABASE_URL"]


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
            if row.get("position") not in ("QB", "RB", "WR", "TE"):
                continue
            if not row.get("gsis_id"):
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
                    row["gsis_id"],
                    row.get("player_name"),
                    row.get("position"),
                    row.get("team"),
                    row.get("jersey_number"),
                ),
            )
    conn.commit()


def _resolve_game_id(sched_df, season, week, team_abbr):
    match = sched_df[
        (sched_df["season"] == season) & (sched_df["week"] == week)
        & ((sched_df["home_team"] == team_abbr) | (sched_df["away_team"] == team_abbr))
    ]
    return match.iloc[0]["game_id"] if len(match) else None


def ingest_weekly_stats(conn, season, week):
    weekly_df = nfl.import_weekly_data([season], downcast=True)
    weekly_df = weekly_df[weekly_df["week"] == week]
    sched_df = nfl.import_schedules([season])

    inserted, skipped = 0, 0
    with conn.cursor() as cur:
        for _, r in weekly_df.iterrows():
            game_id = _resolve_game_id(sched_df, season, week, r.get("recent_team"))
            if not game_id or not r.get("player_id"):
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
                    "team_id": r.get("recent_team"),
                    "completions": r.get("completions"),
                    "attempts": r.get("attempts"),
                    "passing_yards": r.get("passing_yards"),
                    "passing_tds": r.get("passing_tds"),
                    "interceptions": r.get("interceptions"),
                    "passing_epa": r.get("passing_epa"),
                    "cpoe": r.get("cpoe"),
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
                    "fantasy_points_ppr": r.get("fantasy_points_ppr"),
                },
            )
            inserted += 1
    conn.commit()
    print(f"Weekly stats: inserted/updated {inserted}, skipped {skipped} (no game_id match) for {season} wk{week}")


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


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    args = parser.parse_args()

    with psycopg.connect(DB_URL) as conn:
        ingest_teams(conn)
        ingest_games(conn, args.season)
        ingest_players(conn, args.season)
        ingest_weekly_stats(conn, args.season, args.week)
        ingest_snap_counts(conn, args.season, args.week)
