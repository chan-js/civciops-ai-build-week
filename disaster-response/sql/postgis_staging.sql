-- PostgreSQL + PostGIS blueprint only, not executed in this prototype.
-- Keep private staging tables out of publicly exposed endpoints.
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE TABLE IF NOT EXISTS road_observation (
    observation_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    road_id text NOT NULL,
    geom geometry(LineString,4326) NOT NULL,
    status text NOT NULL CHECK (status IN ('open','closed','unverified')),
    observed_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    source_uri text NOT NULL,
    CHECK (expires_at >= observed_at)
);
CREATE INDEX IF NOT EXISTS road_observation_geom_idx
ON road_observation USING gist(geom);
CREATE TABLE IF NOT EXISTS hazard_footprint (
    hazard_id text PRIMARY KEY,
    hazard_type text NOT NULL,
    geom geometry(MultiPolygon,4326) NOT NULL,
    valid_from timestamptz NOT NULL,
    valid_to timestamptz NOT NULL,
    source_uri text NOT NULL,
    CHECK (valid_to >= valid_from)
);
CREATE INDEX IF NOT EXISTS hazard_footprint_geom_idx
ON hazard_footprint USING gist(geom);
-- Intersecting a hazard means review/exclude; it does NOT infer safe passability
-- for nonintersecting roads. Use newest verified observations by road ID.
CREATE OR REPLACE VIEW road_hazard_review AS
SELECT r.road_id,h.hazard_id,r.observed_at,r.status
FROM road_observation r JOIN hazard_footprint h ON ST_Intersects(r.geom,h.geom)
WHERE CURRENT_TIMESTAMP BETWEEN h.valid_from AND h.valid_to;
