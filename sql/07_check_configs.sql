-- Section 3.1: verify the three chunk configurations
\pset pager off

\echo '=== 1. Chunk interval per hypertable ==='
SELECT hypertable_name, column_name, time_interval
FROM timescaledb_information.dimensions
WHERE hypertable_name IN ('energy_readings','energy_readings_3h','energy_readings_week')
ORDER BY time_interval;

\echo '=== 2. Chunk count and chunk range coverage ==='
SELECT hypertable_name,
       count(*)         AS chunk_count,
       min(range_start) AS first_chunk_start,
       max(range_end)   AS last_chunk_end
FROM timescaledb_information.chunks
WHERE hypertable_name IN ('energy_readings','energy_readings_3h','energy_readings_week')
GROUP BY hypertable_name
ORDER BY chunk_count DESC;

\echo '=== 3. Compression status (must be off for all three) ==='
SELECT hypertable_name, num_chunks, compression_enabled
FROM timescaledb_information.hypertables
WHERE hypertable_name IN ('energy_readings','energy_readings_3h','energy_readings_week')
ORDER BY hypertable_name;

\echo '=== 4. Indexes (same method, columns and order on all three) ==='
SELECT tablename, indexname, indexdef
FROM pg_indexes
WHERE tablename IN ('energy_readings','energy_readings_3h','energy_readings_week')
ORDER BY tablename, indexname;

\echo '=== 5. Data checks ==='
WITH s AS (
  SELECT 'energy_readings (1 day)' AS config, count(*) AS row_count,
         count(DISTINCT meter_id) AS meters, min(event_time) AS earliest,
         max(event_time) AS latest, sum(power_kw) AS sum_power, sum(energy_kwh) AS sum_energy
  FROM energy_readings
  UNION ALL
  SELECT 'energy_readings_3h (3 hours)', count(*), count(DISTINCT meter_id),
         min(event_time), max(event_time), sum(power_kw), sum(energy_kwh)
  FROM energy_readings_3h
  UNION ALL
  SELECT 'energy_readings_week (1 week)', count(*), count(DISTINCT meter_id),
         min(event_time), max(event_time), sum(power_kw), sum(energy_kwh)
  FROM energy_readings_week
),
base AS (SELECT * FROM s WHERE config LIKE 'energy_readings (%')
SELECT s.config, s.row_count, s.meters, s.earliest, s.latest,
       round(s.sum_power::numeric, 6)  AS sum_power_kw,
       round(s.sum_energy::numeric, 6) AS sum_energy_kwh,
       (s.row_count = 10643735 AND s.meters = 4000
        AND s.earliest = base.earliest AND s.latest = base.latest
        AND abs(s.sum_power - base.sum_power) <= 0.001
        AND abs(s.sum_energy - base.sum_energy) <= 0.001) AS all_checks_pass
FROM s, base
ORDER BY s.config;