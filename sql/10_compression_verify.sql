-- Section 4.1: verify same chunk ranges compressed, repeat 3.1 data checks
\pset pager off
ANALYZE energy_time_compressed;
ANALYZE energy_meter_compressed;

\echo '=== 1. Compressed-chunk lists side by side (same ranges in both tables) ==='
SELECT a.range_start, a.range_end,
       a.chunk_name AS time_chunk,  a.is_compressed AS time_compressed,
       b.chunk_name AS meter_chunk, b.is_compressed AS meter_compressed
FROM (SELECT * FROM timescaledb_information.chunks WHERE hypertable_name = 'energy_time_compressed') a
FULL JOIN (SELECT * FROM timescaledb_information.chunks WHERE hypertable_name = 'energy_meter_compressed') b
  USING (range_start, range_end)
ORDER BY a.range_start;

\echo '=== 2. Summary: same chunk ranges compressed? ==='
SELECT count(*) AS chunk_ranges,
       count(*) FILTER (WHERE a.is_compressed) AS time_table_compressed,
       count(*) FILTER (WHERE b.is_compressed) AS meter_table_compressed,
       bool_and(a.is_compressed IS NOT DISTINCT FROM b.is_compressed) AS same_ranges_compressed,
       (SELECT cutoff FROM compression_experiment) AS cutoff_used
FROM (SELECT * FROM timescaledb_information.chunks WHERE hypertable_name = 'energy_time_compressed') a
FULL JOIN (SELECT * FROM timescaledb_information.chunks WHERE hypertable_name = 'energy_meter_compressed') b
  USING (range_start, range_end);

\echo '=== 3. Policies still paused ==='
SELECT job_id, hypertable_name, scheduled, config
FROM timescaledb_information.jobs
WHERE hypertable_name IN ('energy_time_compressed', 'energy_meter_compressed')
ORDER BY hypertable_name;

\echo '=== 4. Data checks (repeat of 3.1) ==='
WITH s AS (
  SELECT 'energy_readings (baseline)' AS config, count(*) AS row_count,
         count(DISTINCT meter_id) AS meters, min(event_time) AS earliest,
         max(event_time) AS latest, sum(power_kw) AS sum_power, sum(energy_kwh) AS sum_energy
  FROM energy_readings
  UNION ALL
  SELECT 'energy_time_compressed', count(*), count(DISTINCT meter_id),
         min(event_time), max(event_time), sum(power_kw), sum(energy_kwh)
  FROM energy_time_compressed
  UNION ALL
  SELECT 'energy_meter_compressed', count(*), count(DISTINCT meter_id),
         min(event_time), max(event_time), sum(power_kw), sum(energy_kwh)
  FROM energy_meter_compressed
),
base AS (SELECT * FROM s WHERE config LIKE 'energy_readings%')
SELECT s.config, s.row_count, s.meters, s.earliest, s.latest,
       round(s.sum_power::numeric, 6)  AS sum_power_kw,
       round(s.sum_energy::numeric, 6) AS sum_energy_kwh,
       (s.row_count = 10643735 AND s.meters = 4000
        AND s.earliest = base.earliest AND s.latest = base.latest
        AND abs(s.sum_power - base.sum_power) <= 0.001
        AND abs(s.sum_energy - base.sum_energy) <= 0.001) AS all_checks_pass
FROM s, base
ORDER BY s.config;