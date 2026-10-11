-- Section 3.1: create 3-hour and 1-week hypertables, copy cleaned data,
-- and create identical indexes on all three chunk configurations.
\timing on
SET work_mem = '64MB';

DROP TABLE IF EXISTS energy_readings_3h;
DROP TABLE IF EXISTS energy_readings_week;

CREATE TABLE energy_readings_3h (
    meter_id BIGINT, event_time TIMESTAMPTZ NOT NULL, received_time TIMESTAMPTZ,
    power_kw DOUBLE PRECISION, voltage_v DOUBLE PRECISION, current_a DOUBLE PRECISION,
    frequency_hz DOUBLE PRECISION, energy_kwh DOUBLE PRECISION);
SELECT create_hypertable('energy_readings_3h',
       by_range('event_time', INTERVAL '3 hours'), create_default_indexes => FALSE);

CREATE TABLE energy_readings_week (
    meter_id BIGINT, event_time TIMESTAMPTZ NOT NULL, received_time TIMESTAMPTZ,
    power_kw DOUBLE PRECISION, voltage_v DOUBLE PRECISION, current_a DOUBLE PRECISION,
    frequency_hz DOUBLE PRECISION, energy_kwh DOUBLE PRECISION);
SELECT create_hypertable('energy_readings_week',
       by_range('event_time', INTERVAL '1 week'), create_default_indexes => FALSE);

\echo '=== Copy cleaned rows ==='
INSERT INTO energy_readings_3h   SELECT * FROM energy_readings ORDER BY event_time;
INSERT INTO energy_readings_week SELECT * FROM energy_readings ORDER BY event_time;

\echo '=== Identical non-unique B-tree indexes (ascending) on all three ==='
CREATE INDEX IF NOT EXISTS ix_er_day_time        ON energy_readings      USING btree (event_time);
CREATE INDEX IF NOT EXISTS ix_er_day_meter_time  ON energy_readings      USING btree (meter_id, event_time);
CREATE INDEX IF NOT EXISTS ix_er_3h_time         ON energy_readings_3h   USING btree (event_time);
CREATE INDEX IF NOT EXISTS ix_er_3h_meter_time   ON energy_readings_3h   USING btree (meter_id, event_time);
CREATE INDEX IF NOT EXISTS ix_er_week_time       ON energy_readings_week USING btree (event_time);
CREATE INDEX IF NOT EXISTS ix_er_week_meter_time ON energy_readings_week USING btree (meter_id, event_time);

\echo '=== Update planner statistics ==='
ANALYZE energy_readings;
ANALYZE energy_readings_3h;
ANALYZE energy_readings_week;