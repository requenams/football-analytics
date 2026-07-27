-- Player database schema.
--
-- Two design principles, both a direct consequence of what the pilot taught us:
--
-- 1. MULTI-LEAGUE FROM DAY ONE. Switzerland is a row in `competitions`, not a
--    special case. Adding a league must never require touching the schema.
--
-- 2. ABSENCE IS DATA. Most databases only store players who played. Here
--    `squad_memberships` includes everyone and `match_availability` records
--    why someone didn't play. That is what makes the selection model possible,
--    and it is what no public dataset ships ready-made.

CREATE TABLE IF NOT EXISTS competitions (
    competition_id   VARCHAR PRIMARY KEY,   -- Transfermarkt code: C1, GB1, L1...
    name             VARCHAR NOT NULL,
    country          VARCHAR,
    tier             INTEGER,               -- 1 = top division
    source           VARCHAR                -- where it came from
);

CREATE TABLE IF NOT EXISTS clubs (
    club_id          BIGINT PRIMARY KEY,
    name             VARCHAR NOT NULL,
    competition_id   VARCHAR,
    FOREIGN KEY (competition_id) REFERENCES competitions(competition_id)
);

CREATE TABLE IF NOT EXISTS players (
    player_id        BIGINT PRIMARY KEY,    -- Transfermarkt id: the master key
    name             VARCHAR NOT NULL,
    name_normalized  VARCHAR,               -- accent-stripped, lowercased, for the crosswalk
    date_of_birth    DATE,
    position         VARCHAR,               -- Attack / Midfield / Defender / Goalkeeper
    sub_position     VARCHAR,               -- Left-Back, Centre-Forward...
    foot             VARCHAR,
    height_cm        INTEGER,
    citizenship      VARCHAR
);

-- The cross-source crosswalk. Deliberately kept separate: every source has its
-- own ids and its own spelling of player names, and the matching is imperfect.
-- Storing confidence and method means we can later audit which results depend
-- on shaky matches.
CREATE TABLE IF NOT EXISTS player_xref (
    player_id        BIGINT NOT NULL,
    source           VARCHAR NOT NULL,      -- 'fbref' | 'understat' | 'sofascore'
    source_player_id VARCHAR,
    source_name      VARCHAR,
    confidence       DOUBLE,                -- 0-1
    match_method     VARCHAR,               -- 'exact' | 'fuzzy_dob' | 'manual'
    PRIMARY KEY (player_id, source)
);

-- Who was in the squad, whether or not they played. The table that makes the
-- model possible: without it you can only analyse players who already have
-- minutes, which is precisely the bias we are attacking.
CREATE TABLE IF NOT EXISTS squad_memberships (
    player_id        BIGINT NOT NULL,
    club_id          BIGINT NOT NULL,
    season           INTEGER NOT NULL,      -- start year: 2025 means 2025/26
    joined_date      DATE,
    left_date        DATE,
    on_loan          BOOLEAN,
    market_value_eur BIGINT,
    contract_expiry  DATE,
    PRIMARY KEY (player_id, club_id, season)
);

CREATE TABLE IF NOT EXISTS matches (
    game_id          BIGINT PRIMARY KEY,
    competition_id   VARCHAR,
    season           INTEGER,
    match_date       DATE,
    round            VARCHAR,
    home_club_id     BIGINT,
    away_club_id     BIGINT,
    home_goals       INTEGER,
    away_goals       INTEGER,
    home_manager     VARCHAR,               -- enables the manager-change
    away_manager     VARCHAR                -- identification strategy
);

-- Match-by-match availability. The heart of the project.
--
-- `status` separates the four situations that conventional analysis collapses
-- into a single "didn't play":
--   started        - in the starting eleven
--   substitute_on  - came off the bench
--   unused_sub     - in the squad, fit, not used   <- the strongest signal
--   not_in_squad   - not even named
--   injured        - unavailable through injury     <- NOT a quality signal
--
-- The difference between unused_sub and injured is exactly what separates "not
-- good enough" from "not available", and it is the distinction the model needs
-- in order not to punish players returning from injury.
CREATE TABLE IF NOT EXISTS match_availability (
    game_id          BIGINT NOT NULL,
    player_id        BIGINT NOT NULL,
    club_id          BIGINT,
    status           VARCHAR NOT NULL,
    on_minute        INTEGER,               -- reconstructed from game_events
    off_minute       INTEGER,               -- NULL if they never got on
    minutes          INTEGER DEFAULT 0,
    goals            INTEGER DEFAULT 0,
    assists          INTEGER DEFAULT 0,
    PRIMARY KEY (game_id, player_id)
);

-- Season-aggregated performance stats. Populated from FBref or Understat, not
-- from Transfermarkt. Long format (one row per metric) so that adding new
-- metrics never requires a schema migration: with sources this heterogeneous
-- across leagues, a wide table breaks almost immediately.
CREATE TABLE IF NOT EXISTS player_season_stats (
    player_id        BIGINT NOT NULL,
    competition_id   VARCHAR NOT NULL,
    season           INTEGER NOT NULL,
    source           VARCHAR NOT NULL,
    metric           VARCHAR NOT NULL,      -- 'minutes', 'np_xg', 'xa'...
    value            DOUBLE,
    PRIMARY KEY (player_id, competition_id, season, source, metric)
);

-- Audit log. Every data quality check leaves a trace here, so the state of the
-- data is something you can query rather than something you have to remember.
CREATE TABLE IF NOT EXISTS data_audit (
    checked_at       TIMESTAMP,
    check_name       VARCHAR,
    scope            VARCHAR,
    passed           BOOLEAN,
    detail           VARCHAR
);

CREATE INDEX IF NOT EXISTS idx_avail_player ON match_availability(player_id);
CREATE INDEX IF NOT EXISTS idx_avail_status ON match_availability(status);
CREATE INDEX IF NOT EXISTS idx_squad_season ON squad_memberships(season);
CREATE INDEX IF NOT EXISTS idx_stats_lookup  ON player_season_stats(competition_id, season, metric);