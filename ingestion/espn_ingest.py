"""
Ingest your ESPN Fantasy league (settings, teams, current rosters) via the
unofficial `espn_api` client into leagues / users / league_members / roster_slots.

ESPN has no public Fantasy API — this hits ESPN's internal endpoints the
website itself uses. Private leagues (most of them) need two cookies from a
logged-in browser session:
  1. Log into fantasy.espn.com
  2. Open DevTools -> Application -> Cookies -> https://fantasy.espn.com
  3. Copy the `espn_s2` value and the `SWID` value (keep the surrounding
     braces on SWID, e.g. "{ABCD1234-...}")
These expire periodically (usually when you log out or ESPN rotates the
session) — treat them as short-lived credentials you re-grab, not permanent
secrets. Public leagues need neither.

ESPN gives no crosswalk from its own player ids to nflverse's gsis_id (our
players.player_id), so rostered players are resolved the same way
odds_ingest.py resolves Vegas prop names: fuzzy-match against
players.full_name, cached in player_name_aliases (source='espn'). K/DST
misses are expected and not a bug — nflverse_ingest.py only loads
QB/RB/WR/TE, so there's no players row to match a kicker or defense against
yet; these are counted and skipped rather than guessed.

users / league_members: the ESPN member who owns each team becomes an app
user. users.user_id has no db-generated default, so ids are derived
deterministically from the member's SWID (sha256-truncated to a positive
bigint) — re-running this script updates the same rows instead of minting
duplicates, the same idempotency goal nflverse_ingest.py gets for free from
natural keys.

roster_slots: each run marks this league's currently-active slots dropped,
then re-inserts the live roster with dropped_ts cleared — a full snapshot
diff rather than partial patching, since ESPN's roster endpoint only gives
current state, not move-by-move history.

Not pulled here (out of scope for "get my roster into my app"):
  - draft_slot (league_members) — ESPN doesn't expose original snake-draft
    position in a way that's reliable to infer after the fact, so it's left
    NULL rather than guessed from team_id or round-1 pick order.
  - acquired_via / acquired_ts (roster_slots) — a live roster snapshot
    doesn't carry transaction history; league.recent_activity() could
    backfill this later if it's ever needed.
  - weekly box scores / matchups — a separate future script, not this one.

Run: python espn_ingest.py --season 2026 --league-id 123456
"""

import argparse
import difflib
import hashlib
import os

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json
from espn_api.football import League

DB_URL = os.environ["DATABASE_URL"]
ESPN_S2 = os.environ.get("ESPN_S2")
ESPN_SWID = os.environ.get("ESPN_SWID")

# espn_api's Player.position for D/ST doesn't match our players.position CHECK
# constraint value; lineupSlot strings need the same fixup for roster_slots.slot_type.
POSITION_FIX = {"D/ST": "DST"}
SLOT_TYPE_FIX = {"BE": "BENCH", "RB/WR": "FLEX", "WR/TE": "FLEX", "RB/WR/TE": "FLEX", "D/ST": "DST"}


def stable_id(*parts):
    """Deterministic positive bigint from a natural key ESPN doesn't give us
    as a number (member SWID) — keeps re-runs idempotent instead of minting
    duplicate rows, mirroring how the other ingest scripts key off natural ids."""
    digest = hashlib.sha256(":".join(str(p) for p in parts).encode()).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFFFFFFFFFFFFFF


def infer_scoring_type(settings):
    """ESPN's settings.scoring_type is a coarse enum (e.g. 'H2H_POINTS') that
    doesn't say PPR vs. standard — that's buried in the per-stat scoring
    rules. Look up the points value for receptions (abbr 'REC') instead."""
    rec_rule = next((r for r in settings.scoring_format if r.get("abbr") == "REC"), None)
    pts = rec_rule.get("points") if rec_rule else None
    if pts == 1:
        return "ppr"
    if pts == 0.5:
        return "half_ppr"
    if pts == 0:
        return "std"
    return "custom"


def resolve_player_id(conn, name, min_confidence=0.85):
    """Cache-first fuzzy match, same pattern as odds_ingest.py's resolve_player_id
    — alias_name is a global PK across sources, so a name already resolved for
    Vegas props is reused here for free; new misses are cached with source='espn'."""
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
                VALUES (%s, 'espn', %s, %s, false)
                ON CONFLICT (alias_name) DO NOTHING
                """,
                (name, best_id, round(best_score, 3)),
            )
            conn.commit()
            return best_id
        return None  # no confident match (often a K/DST not in `players` yet) — skip rather than guess wrong


def ingest_league(conn, league, season):
    settings = league.settings
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO leagues (league_id, platform, name, scoring_type, roster_settings_json,
                                  num_teams, waiver_type, faab_budget, season)
            VALUES (%s, 'ESPN-sync', %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (league_id) DO UPDATE SET
                name = EXCLUDED.name,
                scoring_type = EXCLUDED.scoring_type,
                roster_settings_json = EXCLUDED.roster_settings_json,
                num_teams = EXCLUDED.num_teams,
                waiver_type = EXCLUDED.waiver_type,
                faab_budget = EXCLUDED.faab_budget
            """,
            (
                league.league_id,
                settings.name,
                infer_scoring_type(settings),
                Json(settings.position_slot_counts),
                settings.team_count,
                "faab" if settings.faab else "rolling",
                settings.acquisition_budget if settings.faab else 100,
                season,
            ),
        )
    conn.commit()
    print(f"League: '{settings.name}' ({settings.team_count} teams, {infer_scoring_type(settings)})")


def ingest_teams_and_rosters(conn, league):
    # A pre-draft league (offseason, before this season's draft has run)
    # reports every team's roster as empty -- that's real, but it's not a
    # signal that everyone got cut. Guard against the full-snapshot diff
    # below wiping out the last real drafted-roster snapshot (e.g. still
    # showing last season's team while this season is pre-draft): only
    # treat the fetch as authoritative if ESPN actually returned players
    # for at least one team.
    total_rostered = sum(len(team.roster) for team in league.teams)
    if total_rostered == 0:
        print(f"Rosters: league {league.league_id} has 0 players rostered across all teams "
              f"(pre-draft?) -- leaving the existing roster_slots snapshot untouched")
        return

    with conn.cursor() as cur:
        # Full-snapshot diff: close out everything active for this league, then
        # re-open what's actually still rostered below.
        cur.execute(
            "UPDATE roster_slots SET dropped_ts = now() WHERE league_id = %s AND dropped_ts IS NULL",
            (league.league_id,),
        )

        matched, unmatched = 0, 0
        for team in league.teams:
            owner = team.owners[0] if team.owners else None
            member_key = owner.get("id") if owner else f"team:{league.league_id}:{team.team_id}"
            user_id = stable_id("espn-member", member_key)
            display_name = (owner.get("displayName") if owner else None) or team.team_name
            email = f"espn-{str(member_key).strip('{}').lower()}@espn.sync"

            cur.execute(
                """
                INSERT INTO users (user_id, email, display_name)
                VALUES (%s, %s, %s)
                ON CONFLICT (email) DO UPDATE SET display_name = EXCLUDED.display_name
                """,
                (user_id, email, display_name),
            )
            cur.execute(
                """
                INSERT INTO league_members (league_id, user_id, team_name)
                VALUES (%s, %s, %s)
                ON CONFLICT (league_id, user_id) DO UPDATE SET team_name = EXCLUDED.team_name
                """,
                (league.league_id, user_id, team.team_name),
            )

            for p in team.roster:
                player_id = resolve_player_id(conn, p.name)
                if not player_id:
                    unmatched += 1
                    continue
                slot_type = SLOT_TYPE_FIX.get(p.lineupSlot, p.lineupSlot)
                roster_slot_id = stable_id("roster-slot", league.league_id, team.team_id, player_id)
                cur.execute(
                    """
                    INSERT INTO roster_slots (roster_slot_id, league_id, user_id, player_id, slot_type, dropped_ts)
                    VALUES (%s, %s, %s, %s, %s, NULL)
                    ON CONFLICT (roster_slot_id) DO UPDATE SET
                        slot_type = EXCLUDED.slot_type,
                        user_id = EXCLUDED.user_id,
                        dropped_ts = NULL
                    """,
                    (roster_slot_id, league.league_id, user_id, player_id, slot_type),
                )
                matched += 1
    conn.commit()
    print(f"Rosters: {matched} players matched, {unmatched} unmatched "
          f"(check player_name_aliases and whether players table covers that position)")


def ingest_free_agents(conn, league, size=300):
    """Free agents in this league specifically -- percent_owned/percent_started
    on espn_api's Player objects are computed across ALL ESPN leagues (a
    real "how hot is this pickup" signal), but which players are even
    free-agent-eligible is scoped correctly to this league by free_agents().
    Snapshot semantics like ingest_teams_and_rosters(): clear this league's
    prior free-agent rows and reinsert, since size/limit can shift week to
    week and there's no natural key to diff against."""
    agents = league.free_agents(size=size)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM league_free_agents WHERE league_id = %s", (league.league_id,))

    matched, unmatched = 0, 0
    with conn.cursor() as cur:
        for p in agents:
            player_id = resolve_player_id(conn, p.name)
            if not player_id:
                unmatched += 1
                continue
            cur.execute(
                """
                INSERT INTO league_free_agents (league_id, player_id, percent_owned, percent_started, espn_injury_status, captured_ts)
                VALUES (%s, %s, %s, %s, %s, now())
                ON CONFLICT (league_id, player_id) DO UPDATE SET
                    percent_owned = EXCLUDED.percent_owned,
                    percent_started = EXCLUDED.percent_started,
                    espn_injury_status = EXCLUDED.espn_injury_status,
                    captured_ts = now()
                """,
                (league.league_id, player_id, p.percent_owned, p.percent_started, p.injuryStatus),
            )
            matched += 1
    conn.commit()
    print(f"Free agents: {matched} matched, {unmatched} unmatched (of {len(agents)} fetched)")


def print_my_team(league):
    if not ESPN_SWID:
        return
    target = ESPN_SWID.strip("{}").lower()
    mine = next(
        (t for t in league.teams for o in t.owners if o.get("id", "").strip("{}").lower() == target),
        None,
    )
    if mine:
        print(f"Your team: '{mine.team_name}' — {len(mine.roster)} players on roster")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--league-id", type=int, required=True)
    args = parser.parse_args()

    league = League(league_id=args.league_id, year=args.season, espn_s2=ESPN_S2, swid=ESPN_SWID)

    with psycopg.connect(DB_URL) as conn:
        ingest_league(conn, league, args.season)
        ingest_teams_and_rosters(conn, league)
        ingest_free_agents(conn, league)

    print_my_team(league)
    print(f"Done — synced league {args.league_id} ({args.season}), {len(league.teams)} teams.")
