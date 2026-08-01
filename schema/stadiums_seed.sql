-- =====================================================================
-- STADIUM SEED DATA — 2026 season
-- Run once after loading fantasy_kpi_schema.sql (before weather_ingest.py).
-- is_dome = true for fully enclosed AND fixed-roof/covered venues
-- (weather ingestion's only concern is "does rain/wind reach the field").
-- Team relocations reflected: Bills' new Highmark Stadium (opened 2026,
-- still outdoor); Titans/Jaguars/Browns/Commanders remain at their
-- existing outdoor stadiums for 2026 (domed replacements land 2027+).
-- =====================================================================

INSERT INTO stadiums (stadium_id, name, team_id, is_dome, surface, latitude, longitude) VALUES
(1,  'State Farm Stadium',              'ARI', true,  'turf',  33.527600, -112.262600),
(2,  'Mercedes-Benz Stadium',           'ATL', true,  'turf',  33.755400,  -84.400800),
(3,  'M&T Bank Stadium',                'BAL', false, 'grass', 39.278000,  -76.622700),
(4,  'Highmark Stadium',                'BUF', false, 'grass', 42.773800,  -78.786900),
(5,  'Bank of America Stadium',         'CAR', false, 'grass', 35.225800,  -80.852800),
(6,  'Soldier Field',                   'CHI', false, 'grass', 41.862300,  -87.616700),
(7,  'Paycor Stadium',                  'CIN', false, 'turf',  39.095400,  -84.516000),
(8,  'Huntington Bank Field',           'CLE', false, 'grass', 41.506100,  -81.699500),
(9,  'AT&T Stadium',                    'DAL', true,  'turf',  32.747300,  -97.094500),
(10, 'Empower Field at Mile High',      'DEN', false, 'grass', 39.743900, -105.020100),
(11, 'Ford Field',                      'DET', true,  'turf',  42.340000,  -83.045600),
(12, 'Lambeau Field',                   'GB',  false, 'grass', 44.501300,  -88.062200),
(13, 'NRG Stadium',                     'HOU', true,  'turf',  29.684700,  -95.410700),
(14, 'Lucas Oil Stadium',               'IND', true,  'turf',  39.760100,  -86.163900),
(15, 'EverBank Stadium',                'JAX', false, 'grass', 30.323900,  -81.637300),
(16, 'GEHA Field at Arrowhead Stadium', 'KC',  false, 'grass', 39.048900,  -94.483900),
(17, 'Allegiant Stadium',               'LV',  true,  'turf',  36.090900, -115.183300),
(18, 'SoFi Stadium',                    'LAC', true,  'turf',  33.953500, -118.339200),
(19, 'SoFi Stadium',                    'LA',  true,  'turf',  33.953500, -118.339200),
(20, 'Hard Rock Stadium',               'MIA', false, 'grass', 25.958000,  -80.238900),
(21, 'U.S. Bank Stadium',               'MIN', true,  'turf',  44.973700,  -93.257700),
(22, 'Gillette Stadium',                'NE',  false, 'turf',  42.090900,  -71.264300),
(23, 'Caesars Superdome',               'NO',  true,  'turf',  29.951100,  -90.081200),
(24, 'MetLife Stadium',                 'NYG', false, 'turf',  40.813500,  -74.074500),
(25, 'MetLife Stadium',                 'NYJ', false, 'turf',  40.813500,  -74.074500),
(26, 'Lincoln Financial Field',         'PHI', false, 'grass', 39.900800,  -75.167500),
(27, 'Acrisure Stadium',                'PIT', false, 'grass', 40.446800,  -80.015800),
(28, 'Levi''s Stadium',                 'SF',  false, 'grass', 37.403200, -121.969800),
(29, 'Lumen Field',                     'SEA', false, 'turf',  47.595200, -122.331600),
(30, 'Raymond James Stadium',           'TB',  false, 'grass', 27.975900,  -82.503300),
(31, 'Nissan Stadium',                  'TEN', false, 'grass', 36.166500,  -86.771300),
(32, 'Northwest Stadium',               'WAS', false, 'grass', 38.907600,  -76.864500)
ON CONFLICT (stadium_id) DO UPDATE SET
    is_dome = EXCLUDED.is_dome,
    latitude = EXCLUDED.latitude,
    longitude = EXCLUDED.longitude;

-- Link games.stadium_id via home team once games are loaded:
UPDATE games g
SET stadium_id = s.stadium_id
FROM stadiums s
WHERE s.team_id = g.home_team_id AND g.stadium_id IS NULL;
