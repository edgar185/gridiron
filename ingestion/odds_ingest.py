"""
Ingest game lines + player props from The Odds API into vegas_lines / player_props.

Source: https://the-odds-api.com (NOT theoddsapi.com — see their impersonation
warning on-site). Free tier = 500 credits/mo; paid tiers start at $30/mo for 20K.

Handles the two real ID-mapping problems this source has:
  1. Event ids are The Odds API's own — resolved to our games.game_id by
     matching team abbreviations + kickoff time, cached in odds_event_map.
  2. Player props come back as free-text names — resolved via
     player_name_aliases, with a stdlib difflib fuzzy-match fallback that
     inserts new aliases as unverified for later human review.

Run: python odds_ingest.py --season 2026 --week 9
"""

import argparse
import difflib
import os
from datetime import datetime, timezone

import psycopg
import requests
from psycopg.rows import dict_row

DB_URL = os.environ["DATABASE_URL"]
ODDS_API_KEY = os.environ["ODDS_API_KEY"]
BASE_URL = "https://api.the-odds-api.com/v4"
SPORT_KEY = "americanfootball_nfl"

PLAYER_PROP_MARKETS = "player_pass_yds,player_rush_yds,player_reception_yds,player_receptions,player_anytime_td"
GAME_MARKETS = "h2h,spreads,totals"

# The Odds API returns full team names; our schema keys teams by abbreviation.
TEAM_NAME_TO_ABBR = {
    "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL",
    "Buffalo Bills": "BUF", "Carolina Panthers": "CAR", "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE", "Dallas Cowboys": "DAL",
    "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX",
    "Kansas City Chiefs": "KC", "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC",
    "Los Angeles Rams": "LA", "Miami Dolphins": "MIA", "Minnesota Vikings": "MIN",
    "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG",
    "New York Jets": "NYJ", "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT",
    "San Francisco 49ers": "SF", "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans": "TEN", "Washington Commanders": "WAS",
}


def fetch_game_lines():
    resp = requests.get(
        f"{BASE_URL}/sports/{SPORT_KEY}/odds",
        params={"apiKey": ODDS_API_KEY, "regions": "us", "markets": GAME_MARKETS, "oddsFormat": "american"},
    )
    resp.raise_for_status()
    print(f"Game lines — credits used: {resp.headers.get('x-requests-used')}, "
          f"remaining: {resp.headers.get('x-requests-remaining')}")
    return resp.json()


def fetch_events():
    resp = requests.get(f"{BASE_URL}/sports/{SPORT_KEY}/events", params={"apiKey": ODDS_API_KEY})
    resp.raise_for_status()
    return resp.json()


def fetch_player_props(event_id):
    resp = requests.get(
        f"{BASE_URL}/sports/{SPORT_KEY}/events/{event_id}/odds",
        params={"apiKey": ODDS_API_KEY, "regions": "us", "markets": PLAYER_PROP_MARKETS, "oddsFormat": "american"},
    )
    resp.raise_for_status()
    return resp.json()


def resolve_game_id(conn, odds_event_id, home_team_name, away_team_name, commence_time):
    """Cache-first lookup: odds_event_map, else match games by team+week, then cache it."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT game_id FROM odds_event_map WHERE odds_event_id = %s", (odds_event_id,))
        cached = cur.fetchone()
        if cached:
            return cached["game_id"]

        home_abbr = TEAM_NAME_TO_ABBR.get(home_team_name)
        away_abbr = TEAM_NAME_TO_ABBR.get(away_team_name)
        if not home_abbr or not away_abbr:
            return None

        cur.execute(
            """
            SELECT game_id FROM games
            WHERE home_team_id = %s AND away_team_id = %s
              AND kickoff_ts::date = %s::date
            """,
            (home_abbr, away_abbr, commence_time),
        )
        match = cur.fetchone()
        if not match:
            return None

        cur.execute(
            "INSERT INTO odds_event_map (odds_event_id, game_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (odds_event_id, match["game_id"]),
        )
        conn.commit()
        return match["game_id"]


def resolve_player_id(conn, name, min_confidence=0.85):
    """Cache-first: player_name_aliases, else fuzzy-match against players.full_name
    (stdlib difflib — no extra dependency), caching the result as unverified."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT player_id FROM player_name_aliases WHERE alias_name = %s", (name,))
        cached = cur.fetchone()
        if cached:
            return cached["player_id"]

        cur.execute("SELECT player_id, full_name FROM players")
        candidates = cur.fetchall()
        best_id, best_score = None, 0.0
        for c in candidates:
            score = difflib.SequenceMatcher(None, name.lower(), c["full_name"].lower()).ratio()
            if score > best_score:
                best_id, best_score = c["player_id"], score

        if best_score >= min_confidence:
            cur.execute(
                """
                INSERT INTO player_name_aliases (alias_name, source, player_id, confidence, verified)
                VALUES (%s, 'the_odds_api', %s, %s, false)
                ON CONFLICT (alias_name) DO NOTHING
                """,
                (name, best_id, round(best_score, 3)),
            )
            conn.commit()
            return best_id
        return None  # no confident match — skip this prop rather than guess wrong


def store_game_lines(conn, games):
    now = datetime.now(timezone.utc)
    stored, unmatched = 0, 0
    with conn.cursor() as cur:
        for g in games:
            game_id = resolve_game_id(conn, g["id"], g["home_team"], g["away_team"], g["commence_time"])
            if not game_id:
                unmatched += 1
                continue

            spreads = next((m for bm in g.get("bookmakers", []) for m in bm["markets"] if m["key"] == "spreads"), None)
            totals = next((m for bm in g.get("bookmakers", []) for m in bm["markets"] if m["key"] == "totals"), None)
            # outcomes[0] is NOT reliably the home team -- The Odds API orders
            # spread outcomes arbitrarily (confirmed live: a Seahawks-home game
            # came back with the Patriots listed first). Match by name instead;
            # totals market is order-safe since both outcomes share one point.
            home_outcome = next((o for o in spreads["outcomes"] if o["name"] == g["home_team"]), None) if spreads else None
            spread_val = home_outcome["point"] if home_outcome else None
            total_val = totals["outcomes"][0]["point"] if totals else None

            cur.execute(
                """
                INSERT INTO vegas_lines (game_id, captured_ts, source, spread, total,
                                          home_implied_total, away_implied_total)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (game_id, captured_ts, source) DO NOTHING
                """,
                (
                    game_id, now, "the_odds_api", spread_val, total_val,
                    (total_val / 2 - spread_val / 2) if total_val and spread_val else None,
                    (total_val / 2 + spread_val / 2) if total_val and spread_val else None,
                ),
            )
            stored += 1
    conn.commit()
    print(f"Game lines: stored {stored}, unmatched (no game_id resolved) {unmatched}")


def store_player_props(conn, event_id, game_id, props_payload):
    now = datetime.now(timezone.utc)
    stored, unmatched = 0, 0
    with conn.cursor() as cur:
        for bookmaker in props_payload.get("bookmakers", []):
            for market in bookmaker.get("markets", []):
                for outcome in market.get("outcomes", []):
                    player_name = outcome.get("description")
                    player_id = resolve_player_id(conn, player_name) if player_name else None
                    if not player_id:
                        unmatched += 1
                        continue
                    cur.execute(
                        """
                        INSERT INTO player_props (prop_id, player_id, game_id, market, line,
                                                   over_odds, under_odds, captured_ts, source)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT DO NOTHING
                        """,
                        (
                            f"{event_id}:{market['key']}:{player_name}:{bookmaker['key']}",
                            player_id, game_id, market["key"], outcome.get("point"),
                            outcome.get("price") if outcome.get("name") == "Over" else None,
                            outcome.get("price") if outcome.get("name") == "Under" else None,
                            now, bookmaker["key"],
                        ),
                    )
                    stored += 1
    conn.commit()
    if unmatched:
        print(f"  props for event {event_id}: stored {stored}, unmatched player names {unmatched} (check player_name_aliases)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--skip-props", action="store_true",
                         help="Skip player props (5 markets x ~16 events/week is the "
                              "expensive part of the free 500-credit/mo quota). Nothing "
                              "downstream reads player_props yet -- only vegas_lines "
                              "(game lines) feeds the app -- so scheduled/frequent runs "
                              "should pass this.")
    args = parser.parse_args()

    with psycopg.connect(DB_URL) as conn:
        games = fetch_game_lines()
        store_game_lines(conn, games)

        if args.skip_props:
            print(f"Done — game lines only (--skip-props) for season {args.season} week {args.week}")
            raise SystemExit(0)

        # fetch_events() returns the WHOLE season's slate (272 games), not
        # just the requested week -- player props are a per-event API call,
        # so looping over all of them regardless of --week would burn the
        # entire monthly credit quota in one run once props are actually
        # posted for the full season. Filter to games in the requested
        # season/week before spending a props call on each one.
        events = fetch_events()
        processed = 0
        for ev in events:
            game_id = resolve_game_id(conn, ev["id"], ev["home_team"], ev["away_team"], ev["commence_time"])
            if not game_id:
                continue
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT season, week FROM games WHERE game_id = %s", (game_id,))
                g = cur.fetchone()
            if not g or g["season"] != args.season or g["week"] != args.week:
                continue
            props = fetch_player_props(ev["id"])
            store_player_props(conn, ev["id"], game_id, props)
            processed += 1

        print(f"Done — processed {processed} events for season {args.season} week {args.week} (of {len(events)} total events fetched)")
