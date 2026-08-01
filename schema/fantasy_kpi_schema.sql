-- =====================================================================
-- FANTASY FOOTBALL DECISION ENGINE — KPI DATABASE SCHEMA
-- Dialect: PostgreSQL 15+
-- Scope: player/team reference data, per-game advanced KPIs, external
--        market signals (Vegas), injuries/news, and derived projections.
--        App-layer tables (users, leagues, rosters) are listed at the
--        bottom as stubs — not the focus of this schema.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. REFERENCE TABLES
-- ---------------------------------------------------------------------

CREATE TABLE teams (
    team_id         VARCHAR(4) PRIMARY KEY,   -- nflverse team abbreviation, e.g. 'KC', 'BUF'
    city            VARCHAR(50) NOT NULL,
    name            VARCHAR(50) NOT NULL,
    conference      VARCHAR(3) CHECK (conference IN ('AFC','NFC')),
    division        VARCHAR(10),
    bye_week        SMALLINT
);

CREATE TABLE players (
    player_id           VARCHAR(10) PRIMARY KEY,   -- nflverse gsis_id, e.g. '00-0034796'
    full_name           VARCHAR(100) NOT NULL,
    position            VARCHAR(4) NOT NULL CHECK (position IN ('QB','RB','WR','TE','K','DST')),
    team_id             VARCHAR(4) REFERENCES teams(team_id),
    jersey_number        SMALLINT,
    birthdate           DATE,
    draft_year          SMALLINT,
    draft_round          SMALLINT,
    draft_pick           SMALLINT,
    height_in           SMALLINT,
    weight_lbs           SMALLINT,
    status              VARCHAR(20) DEFAULT 'active', -- active, ir, suspended, retired
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_players_position ON players(position);
CREATE INDEX idx_players_team ON players(team_id);

CREATE TABLE stadiums (
    stadium_id      SMALLINT PRIMARY KEY,
    name            VARCHAR(100),
    team_id         VARCHAR(4) REFERENCES teams(team_id),
    is_dome         BOOLEAN DEFAULT false,
    surface         VARCHAR(20), -- grass, turf
    latitude        NUMERIC(9,6),   -- required by weather ingestion
    longitude       NUMERIC(9,6)
);

CREATE TABLE games (
    game_id         VARCHAR(20) PRIMARY KEY,   -- nflverse format: '{season}_{week:02d}_{away}_{home}'
    season          SMALLINT NOT NULL,
    week            SMALLINT NOT NULL,
    home_team_id    VARCHAR(4) REFERENCES teams(team_id),
    away_team_id    VARCHAR(4) REFERENCES teams(team_id),
    kickoff_ts      TIMESTAMPTZ NOT NULL,
    stadium_id      SMALLINT REFERENCES stadiums(stadium_id),
    game_status     VARCHAR(20) DEFAULT 'scheduled' -- scheduled, in_progress, final
);
CREATE INDEX idx_games_season_week ON games(season, week);

-- ---------------------------------------------------------------------
-- 2. PER-GAME ADVANCED KPI TABLE (the core decision-engine table)
--    One row per player per game. Nullable columns are position-specific.
-- ---------------------------------------------------------------------

CREATE TABLE player_game_stats (
    player_id               VARCHAR(10) REFERENCES players(player_id),
    game_id                 VARCHAR(20) REFERENCES games(game_id),
    team_id                 VARCHAR(4) REFERENCES teams(team_id),

    -- Usage / Opportunity (all positions)
    snaps_played              SMALLINT,
    snap_pct                 NUMERIC(5,2),
    routes_run                SMALLINT,
    route_participation_pct   NUMERIC(5,2),

    -- Passing (QB)
    dropbacks                SMALLINT,
    completions               SMALLINT,
    pass_attempts             SMALLINT,
    pass_yards                SMALLINT,
    pass_tds                  SMALLINT,
    interceptions             SMALLINT,
    epa_per_dropback           NUMERIC(6,3),
    cpoe                     NUMERIC(5,2),        -- completion % over expected
    any_a                    NUMERIC(5,2),
    air_yards_per_attempt      NUMERIC(5,2),
    play_action_rate           NUMERIC(5,2),
    pressure_rate_allowed      NUMERIC(5,2),
    time_to_throw_avg          NUMERIC(4,2),
    sacks_taken                SMALLINT,
    designed_rush_attempts     SMALLINT,
    rz_pass_attempts          SMALLINT,

    -- Rushing (RB, some QB/WR)
    carries                  SMALLINT,
    rush_yards                SMALLINT,
    rush_tds                  SMALLINT,
    ryoe                     NUMERIC(6,2),        -- rush yards over expected
    yards_after_contact        NUMERIC(6,2),
    missed_tackles_forced      SMALLINT,
    goal_line_carries          SMALLINT,           -- carries inside opp 5

    -- Receiving (RB/WR/TE)
    targets                  SMALLINT,
    receptions                SMALLINT,
    rec_yards                 SMALLINT,
    rec_tds                   SMALLINT,
    air_yards                 SMALLINT,
    adot                     NUMERIC(4,2),         -- avg depth of target
    yprr                     NUMERIC(5,2),         -- yards per route run
    target_share               NUMERIC(5,2),
    air_yards_share            NUMERIC(5,2),
    wopr                     NUMERIC(5,3),         -- weighted opportunity rating
    catch_rate_over_expected    NUMERIC(5,2),
    contested_catch_rate        NUMERIC(5,2),
    yards_after_catch           NUMERIC(6,2),
    rz_targets                SMALLINT,
    end_zone_targets           SMALLINT,
    slot_snap_pct              NUMERIC(5,2),

    -- Fantasy output (all positions)
    fantasy_pts_std            NUMERIC(6,2),
    fantasy_pts_ppr            NUMERIC(6,2),
    fantasy_pts_half_ppr        NUMERIC(6,2),

    PRIMARY KEY (player_id, game_id)
);
CREATE INDEX idx_pgs_player ON player_game_stats(player_id);
CREATE INDEX idx_pgs_game ON player_game_stats(game_id);

-- ---------------------------------------------------------------------
-- 3. ROLLING / TREND AGGREGATES (materialized view, refreshed weekly)
--    Powers the "usage trend" waiver-wire detector.
-- ---------------------------------------------------------------------

CREATE MATERIALIZED VIEW player_trailing_form AS
SELECT
    player_id,
    -- trailing 3-week windows, computed via window functions upstream
    AVG(snap_pct)      OVER w3 AS snap_pct_trail3,
    AVG(target_share)   OVER w3 AS target_share_trail3,
    AVG(route_participation_pct) OVER w3 AS route_pct_trail3,
    AVG(fantasy_pts_ppr) OVER w3 AS fpts_ppr_trail3,
    AVG(yprr)          OVER w5 AS yprr_trail5
FROM player_game_stats
WINDOW
    w3 AS (PARTITION BY player_id ORDER BY game_id ROWS BETWEEN 2 PRECEDING AND CURRENT ROW),
    w5 AS (PARTITION BY player_id ORDER BY game_id ROWS BETWEEN 4 PRECEDING AND CURRENT ROW);

-- ---------------------------------------------------------------------
-- 4. INJURIES & DEPTH CHARTS
-- ---------------------------------------------------------------------

CREATE TABLE injuries (
    injury_id           BIGINT PRIMARY KEY,
    player_id           VARCHAR(10) REFERENCES players(player_id),
    season              SMALLINT,
    week                SMALLINT,
    body_part           VARCHAR(50),
    practice_status_wed   VARCHAR(20), -- DNP, Limited, Full
    practice_status_thu   VARCHAR(20),
    practice_status_fri   VARCHAR(20),
    game_status          VARCHAR(20), -- Questionable, Doubtful, Out, IR
    reported_ts          TIMESTAMPTZ,
    expected_return_week  SMALLINT
);
CREATE INDEX idx_injuries_player_week ON injuries(player_id, season, week);

CREATE TABLE depth_charts (
    team_id      VARCHAR(4) REFERENCES teams(team_id),
    season       SMALLINT,
    week         SMALLINT,
    position     VARCHAR(4),
    player_id    VARCHAR(10) REFERENCES players(player_id),
    depth_rank   SMALLINT,
    PRIMARY KEY (team_id, season, week, position, depth_rank)
);

-- ---------------------------------------------------------------------
-- 5. EXTERNAL MARKET SIGNALS (Vegas)
-- ---------------------------------------------------------------------

CREATE TABLE vegas_lines (
    game_id               VARCHAR(20) REFERENCES games(game_id),
    captured_ts            TIMESTAMPTZ NOT NULL,
    source                VARCHAR(30),
    spread                NUMERIC(4,1),        -- negative = home favored
    total                 NUMERIC(4,1),
    home_implied_total       NUMERIC(4,1),
    away_implied_total       NUMERIC(4,1),
    PRIMARY KEY (game_id, captured_ts, source)
);

CREATE TABLE player_props (
    prop_id       BIGINT PRIMARY KEY,
    player_id     VARCHAR(10) REFERENCES players(player_id),
    game_id       VARCHAR(20) REFERENCES games(game_id),
    market        VARCHAR(40),      -- rush_yds, rec_yds, pass_tds, longest_reception, etc.
    line          NUMERIC(6,1),
    over_odds      SMALLINT,
    under_odds      SMALLINT,
    captured_ts    TIMESTAMPTZ,
    source        VARCHAR(30)
);
CREATE INDEX idx_props_player_game ON player_props(player_id, game_id);

CREATE TABLE weather (
    game_id       VARCHAR(20) PRIMARY KEY REFERENCES games(game_id),
    temp_f        SMALLINT,
    wind_mph       SMALLINT,
    precip_pct     SMALLINT,
    is_dome       BOOLEAN
);

CREATE TABLE defense_matchup_grades (
    team_id             VARCHAR(4) REFERENCES teams(team_id),
    season              SMALLINT,
    week                SMALLINT,
    vs_position          VARCHAR(4),   -- QB, RB, WR_slot, WR_wide, TE
    epa_allowed_per_play    NUMERIC(6,3),
    pts_allowed_per_game     NUMERIC(5,2),
    yprr_allowed           NUMERIC(5,2),
    positional_rank         SMALLINT,     -- 1 (toughest) - 32 (easiest)
    PRIMARY KEY (team_id, season, week, vs_position)
);

-- ---------------------------------------------------------------------
-- 6. DRAFT / VALUATION SUPPORT
-- ---------------------------------------------------------------------

CREATE TABLE adp (
    player_id      VARCHAR(10) REFERENCES players(player_id),
    platform       VARCHAR(30),   -- ESPN, Sleeper, Yahoo, NFC, etc.
    date_captured   DATE,
    avg_pick        NUMERIC(5,1),
    min_pick        SMALLINT,
    max_pick        SMALLINT,
    PRIMARY KEY (player_id, platform, date_captured)
);

-- ---------------------------------------------------------------------
-- 7. MODEL OUTPUT / PROJECTIONS (what the app actually serves)
-- ---------------------------------------------------------------------

CREATE TABLE projections (
    player_id        VARCHAR(10) REFERENCES players(player_id),
    season           SMALLINT,
    week             SMALLINT,
    model_version      VARCHAR(20),
    floor_pts         NUMERIC(5,2),
    median_pts        NUMERIC(5,2),
    ceiling_pts        NUMERIC(5,2),
    confidence_score    SMALLINT CHECK (confidence_score BETWEEN 0 AND 100),
    recommendation      VARCHAR(10),  -- start, sit, flex, add, drop
    rationale_text      TEXT,          -- generated plain-language "why"
    generated_ts       TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (player_id, season, week, model_version)
);
CREATE INDEX idx_projections_week ON projections(season, week);

-- ---------------------------------------------------------------------
-- 8. NEWS / SENTIMENT EVENTS
-- ---------------------------------------------------------------------

CREATE TABLE news_events (
    event_id      BIGINT PRIMARY KEY,
    player_id     VARCHAR(10) REFERENCES players(player_id),
    event_ts       TIMESTAMPTZ,
    headline      TEXT,
    source        VARCHAR(50),
    sentiment_score NUMERIC(4,3),   -- -1.0 to 1.0
    category      VARCHAR(30)     -- injury, depth_chart, suspension, trade, coach_quote
);
CREATE INDEX idx_news_player_ts ON news_events(player_id, event_ts);

-- ---------------------------------------------------------------------
-- 8a. ID CROSSWALKS
--     player_id/team_id/game_id now use nflverse's own natural keys
--     directly (gsis_id, team abbreviation, and nflverse's game_id
--     format), so nflverse ingestion needs no mapping table.
--     The Odds API is the one source with a different identity system
--     (free-text player names, its own event ids) — these two tables
--     resolve that, built once via fuzzy-match + manual review, then
--     reused on every ingest run.
-- ---------------------------------------------------------------------

CREATE TABLE player_name_aliases (
    alias_name     VARCHAR(100) PRIMARY KEY,   -- exact string as returned by an external source
    source         VARCHAR(30) NOT NULL,        -- the_odds_api, espn, sleeper, etc.
    player_id      VARCHAR(10) REFERENCES players(player_id),
    confidence     NUMERIC(4,3),                -- fuzzy-match score at creation time, for audit
    verified       BOOLEAN DEFAULT false        -- true once a human has confirmed the match
);
CREATE INDEX idx_player_aliases_source ON player_name_aliases(source);

CREATE TABLE odds_event_map (
    odds_event_id   VARCHAR(50) PRIMARY KEY,   -- The Odds API's event id
    game_id         VARCHAR(20) REFERENCES games(game_id),
    matched_ts       TIMESTAMPTZ DEFAULT now()
);

-- ---------------------------------------------------------------------
-- 9. USERS, LEAGUES & ROSTERS
-- ---------------------------------------------------------------------

CREATE TABLE users (
    user_id         BIGINT PRIMARY KEY,
    email           VARCHAR(120) UNIQUE NOT NULL,
    display_name     VARCHAR(60),
    created_at       TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE leagues (
    league_id            BIGINT PRIMARY KEY,
    platform             VARCHAR(30),   -- native, ESPN-sync, Sleeper-sync, Yahoo-sync
    name                 VARCHAR(100),
    scoring_type          VARCHAR(20) DEFAULT 'ppr', -- std, half_ppr, ppr, custom
    roster_settings_json    JSONB,        -- {"QB":1,"RB":2,"WR":2,"FLEX":1,"TE":1,"BENCH":6,...}
    num_teams             SMALLINT,
    waiver_type            VARCHAR(20) DEFAULT 'faab', -- faab, rolling, reverse_standings
    faab_budget            SMALLINT DEFAULT 100,
    season                SMALLINT,
    created_at            TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE league_members (
    league_id     BIGINT REFERENCES leagues(league_id),
    user_id       BIGINT REFERENCES users(user_id),
    team_name     VARCHAR(60),
    draft_slot     SMALLINT,   -- 1..num_teams, assigned pre-draft
    PRIMARY KEY (league_id, user_id)
);

CREATE TABLE roster_slots (
    roster_slot_id   BIGINT PRIMARY KEY,
    league_id        BIGINT REFERENCES leagues(league_id),
    user_id          BIGINT REFERENCES users(user_id),
    player_id        VARCHAR(10) REFERENCES players(player_id),
    slot_type         VARCHAR(10),   -- QB, RB, WR, TE, FLEX, BENCH, IR
    acquired_via       VARCHAR(20),   -- draft, waiver, trade, free_agent
    acquired_ts        TIMESTAMPTZ,
    dropped_ts         TIMESTAMPTZ    -- null while active on roster
);
CREATE INDEX idx_roster_slots_league_user ON roster_slots(league_id, user_id) WHERE dropped_ts IS NULL;

-- ---------------------------------------------------------------------
-- 10. LIVE DRAFT STATE
--     Backs "picks until your turn", VONA, and the draft-room UI.
-- ---------------------------------------------------------------------

CREATE TABLE drafts (
    draft_id           BIGINT PRIMARY KEY,
    league_id          BIGINT REFERENCES leagues(league_id),
    draft_type          VARCHAR(20) DEFAULT 'snake', -- snake, linear, auction
    num_rounds          SMALLINT,
    pick_time_seconds     SMALLINT DEFAULT 90,
    status              VARCHAR(20) DEFAULT 'scheduled', -- scheduled, in_progress, paused, complete
    scheduled_start_ts    TIMESTAMPTZ,
    started_at          TIMESTAMPTZ,
    completed_at         TIMESTAMPTZ
);

-- Pre-computed draft order: one row per (draft, overall pick number).
-- Generated at draft creation time from league_members.draft_slot + snake/linear logic —
-- this is what makes "picks until your turn" an O(1) lookup instead of live math.
CREATE TABLE draft_order (
    draft_id        BIGINT REFERENCES drafts(draft_id),
    pick_number      INTEGER,   -- overall pick, 1-indexed
    round           SMALLINT,
    slot_in_round     SMALLINT,
    user_id         BIGINT REFERENCES users(user_id),
    PRIMARY KEY (draft_id, pick_number)
);
CREATE INDEX idx_draft_order_user ON draft_order(draft_id, user_id);

-- Actual picks made, filled in as the draft progresses.
CREATE TABLE draft_picks (
    draft_id        BIGINT REFERENCES drafts(draft_id),
    pick_number      INTEGER,
    player_id        VARCHAR(10) REFERENCES players(player_id),
    user_id         BIGINT REFERENCES users(user_id),
    picked_ts        TIMESTAMPTZ DEFAULT now(),
    is_auto_pick      BOOLEAN DEFAULT false,   -- clock expired, engine auto-selected BPA
    auction_amount    NUMERIC(6,2),            -- null unless draft_type = 'auction'
    PRIMARY KEY (draft_id, pick_number)
);
CREATE INDEX idx_draft_picks_player ON draft_picks(draft_id, player_id);

-- User's pre-draft queue / ranked watchlist, consumed by the tier board's
-- "your queue" rail and used for auto-pick fallback.
CREATE TABLE draft_queues (
    draft_id      BIGINT REFERENCES drafts(draft_id),
    user_id       BIGINT REFERENCES users(user_id),
    player_id     VARCHAR(10) REFERENCES players(player_id),
    queue_rank     SMALLINT,
    PRIMARY KEY (draft_id, user_id, player_id)
);

-- Convenience view: for every draft, each user's next upcoming pick number
-- and how many picks separate it from the current pick. Powers the
-- ScarcityMeter's "N PICKS TO YOU" directly.
CREATE VIEW draft_picks_until_turn AS
SELECT
    do_next.draft_id,
    do_next.user_id,
    do_next.pick_number       AS next_pick_number,
    do_next.pick_number - cur.current_pick AS picks_until_turn
FROM draft_order do_next
JOIN LATERAL (
    SELECT COALESCE(MAX(pick_number), 0) + 1 AS current_pick
    FROM draft_picks
    WHERE draft_picks.draft_id = do_next.draft_id
) cur ON true
WHERE do_next.pick_number >= cur.current_pick
  AND do_next.pick_number = (
        SELECT MIN(pick_number) FROM draft_order
        WHERE draft_id = do_next.draft_id
          AND user_id = do_next.user_id
          AND pick_number >= cur.current_pick
  );

-- ---------------------------------------------------------------------
-- 11. WAIVERS & TRANSACTIONS
-- ---------------------------------------------------------------------

CREATE TABLE waiver_claims (
    claim_id        BIGINT PRIMARY KEY,
    league_id        BIGINT REFERENCES leagues(league_id),
    user_id         BIGINT REFERENCES users(user_id),
    player_id        VARCHAR(10) REFERENCES players(player_id),
    drop_player_id     VARCHAR(10) REFERENCES players(player_id),  -- nullable, roster spot freed
    faab_bid         NUMERIC(5,2),
    week             SMALLINT,
    priority         SMALLINT,      -- for rolling/reverse-standings waiver types
    status           VARCHAR(20) DEFAULT 'pending', -- pending, won, lost, cancelled
    submitted_ts       TIMESTAMPTZ DEFAULT now(),
    processed_ts       TIMESTAMPTZ
);
CREATE INDEX idx_waiver_claims_league_week ON waiver_claims(league_id, week, status);

CREATE TABLE transactions (
    transaction_id    BIGINT PRIMARY KEY,
    league_id         BIGINT REFERENCES leagues(league_id),
    type              VARCHAR(20),   -- draft_pick, waiver_add, free_agent_add, drop, trade
    payload_json        JSONB,         -- e.g. trade: {"from_user":..,"to_user":..,"players":[...]}
    created_ts          TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_transactions_league ON transactions(league_id, created_ts);
