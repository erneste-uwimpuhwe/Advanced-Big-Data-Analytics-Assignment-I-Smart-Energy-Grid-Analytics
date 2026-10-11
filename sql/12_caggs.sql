-- Section 6.1: three continuous aggregates over energy_readings
\pset pager off
SET work_mem = '64MB';

DROP MATERIALIZED VIEW IF EXISTS cagg_15min_region CASCADE;
DROP MATERIALIZED VIEW IF EXISTS cagg_hour_region  CASCADE;
DROP MATERIALIZED VIEW IF EXISTS cagg_day_meter    CASCADE;

-- 15-minute bucket x region (inner join to meters)
CREATE MATERIALIZED VIEW cagg_15min_region
WITH (timescaledb.continuous, timescaledb.materialized_only = true) AS
SELECT time_bucket(INTERVAL '15 minutes', e.event_time) AS bucket,
       m.region,
       sum(e.energy_kwh) AS sum_energy_kwh,
       sum(e.power_kw)   AS sum_power_kw,
       count(*)          AS reading_count
FROM energy_readings e
INNER JOIN meters m ON m.meter_id = e.meter_id
GROUP BY time_bucket(INTERVAL '15 minutes', e.event_time), m.region
WITH NO DATA;

-- CAT hour x region (inner join to meters)
CREATE MATERIALIZED VIEW cagg_hour_region
WITH (timescaledb.continuous, timescaledb.materialized_only = true) AS
SELECT time_bucket(INTERVAL '1 hour', e.event_time, 'Africa/Kigali') AS bucket,
       m.region,
       sum(e.energy_kwh) AS sum_energy_kwh,
       sum(e.power_kw)   AS sum_power_kw,
       count(*)          AS reading_count
FROM energy_readings e
INNER JOIN meters m ON m.meter_id = e.meter_id
GROUP BY time_bucket(INTERVAL '1 hour', e.event_time, 'Africa/Kigali'), m.region
WITH NO DATA;

-- CAT day x meter_id
CREATE MATERIALIZED VIEW cagg_day_meter
WITH (timescaledb.continuous, timescaledb.materialized_only = true) AS
SELECT time_bucket(INTERVAL '1 day', event_time, 'Africa/Kigali') AS bucket,
       meter_id,
       sum(energy_kwh) AS sum_energy_kwh,
       sum(power_kw)   AS sum_power_kw,
       count(*)        AS reading_count
FROM energy_readings
GROUP BY time_bucket(INTERVAL '1 day', event_time, 'Africa/Kigali'), meter_id
WITH NO DATA;

\echo '=== Views are initially empty ==='
SELECT 'cagg_15min_region' AS view_name, count(*) AS rows FROM cagg_15min_region
UNION ALL SELECT 'cagg_hour_region', count(*) FROM cagg_hour_region
UNION ALL SELECT 'cagg_day_meter',   count(*) FROM cagg_day_meter;

\echo '=== Manual refresh of the entire generated period (timed) ==='
\timing on
CALL refresh_continuous_aggregate('cagg_15min_region', '2026-09-01 00:00:00+02', '2026-09-29 00:00:00+02');
CALL refresh_continuous_aggregate('cagg_hour_region',  '2026-09-01 00:00:00+02', '2026-09-29 00:00:00+02');
CALL refresh_continuous_aggregate('cagg_day_meter',    '2026-09-01 00:00:00+02', '2026-09-29 00:00:00+02');
\timing off

\echo '=== Rows after refresh ==='
SELECT 'cagg_15min_region' AS view_name, count(*) AS rows FROM cagg_15min_region
UNION ALL SELECT 'cagg_hour_region', count(*) FROM cagg_hour_region
UNION ALL SELECT 'cagg_day_meter',   count(*) FROM cagg_day_meter;