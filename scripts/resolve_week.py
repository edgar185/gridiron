"""
Figures out which (season, current_week, stats_week) the live-refresh
orchestrator should ingest, from the real games table -- no hardcoded
week number to keep updated by hand.

current_week: the nearest week that hasn't fully finished yet (what odds/
  props should be priced for).
stats_week: the most recently *completed* week (2+ days past its last
  kickoff, to clear Monday night games) -- what nflverse stats/projections
  should run against. 0 before the season's first week has finished.

Prints shell-eval-able output: SEASON=... CURRENT_WEEK=... STATS_WEEK=...
"""

import os
from datetime import datetime, timezone

import psycopg

DB_URL = os.environ["DATABASE_URL"]


def resolve():
    now = datetime.now(timezone.utc)
    # A season's games run Sept of year Y through early Feb of Y+1. Roll
    # over the "current season" label at March 1 -- safely after the
    # Super Bowl, safely before the next season's schedule is needed.
    season = now.year if now.month >= 3 else now.year - 1

    with psycopg.connect(DB_URL) as conn:
        rows = conn.execute(
            "SELECT week, min(kickoff_ts), max(kickoff_ts) FROM games "
            "WHERE season = %s GROUP BY week ORDER BY week",
            (season,),
        ).fetchall()

    if not rows:
        return season, 1, 0

    current_week, stats_week = None, 0
    for week, _start, end in rows:
        if (now - end).days >= 2:
            stats_week = week
        if current_week is None and now <= end:
            current_week = week
    if current_week is None:
        current_week = rows[-1][0]  # past the last scheduled week (offseason)

    return season, current_week, stats_week


if __name__ == "__main__":
    season, current_week, stats_week = resolve()
    print(f"SEASON={season}")
    print(f"CURRENT_WEEK={current_week}")
    print(f"STATS_WEEK={stats_week}")
