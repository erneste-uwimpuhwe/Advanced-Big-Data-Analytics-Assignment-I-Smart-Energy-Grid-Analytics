-- Section 4.2: storage, compression ratio, % saved, compressed chunks/rows, cost
\pset pager off

\echo '=== 1. Sizes (all chunks, compressed and uncompressed, with indexes) ==='
WITH sz AS (
  SELECT 'energy_readings (baseline, 1 day)' AS cfg, 1 AS ord, * FROM hypertable_detailed_size('energy_readings')
  UNION ALL
  SELECT 'energy_time_compressed', 2, * FROM hypertable_detailed_size('energy_time_compressed')
  UNION ALL
  SELECT 'energy_meter_compressed', 3, * FROM hypertable_detailed_size('energy_meter_compressed')
),
b AS (SELECT total_bytes AS base_total FROM sz WHERE ord = 1)
SELECT cfg,
       round(table_bytes / 1048576.0, 1) AS data_mb,
       round(index_bytes / 1048576.0, 1) AS index_mb,
       round(toast_bytes / 1048576.0, 1) AS toast_mb,
       round(total_bytes / 1048576.0, 1) AS total_mb,
       round(b.base_total::numeric / total_bytes, 2) AS compression_ratio,
       round(100.0 * (b.base_total - total_bytes) / b.base_total, 2) AS pct_saved
FROM sz, b
ORDER BY ord;

\echo '=== 2. TimescaleDB compression statistics (before vs after, per table) ==='
SELECT 'energy_time_compressed' AS hypertable, total_chunks, number_compressed_chunks,
       pg_size_pretty(before_compression_total_bytes) AS before_total,
       pg_size_pretty(after_compression_total_bytes)  AS after_total
FROM hypertable_compression_stats('energy_time_compressed')
UNION ALL
SELECT 'energy_meter_compressed', total_chunks, number_compressed_chunks,
       pg_size_pretty(before_compression_total_bytes),
       pg_size_pretty(after_compression_total_bytes)
FROM hypertable_compression_stats('energy_meter_compressed');

\echo '=== 3. Compressed chunks and % of rows held in compressed chunks ==='
WITH c AS (
  SELECT hypertable_name, range_start, range_end, is_compressed
  FROM timescaledb_information.chunks
  WHERE hypertable_name IN ('energy_time_compressed', 'energy_meter_compressed')
),
r AS (
  SELECT c.*, (SELECT count(*) FROM energy_readings e
               WHERE e.event_time >= c.range_start AND e.event_time < c.range_end) AS original_rows
  FROM c
)
SELECT hypertable_name,
       count(*) FILTER (WHERE is_compressed) || ' of ' || count(*) AS compressed_chunks,
       sum(original_rows) FILTER (WHERE is_compressed) AS rows_in_compressed_chunks,
       round(100.0 * sum(original_rows) FILTER (WHERE is_compressed) / 10643735, 2) AS pct_rows_compressed
FROM r
GROUP BY hypertable_name
ORDER BY hypertable_name;

\echo '=== 4. Compression cost (sum of measured chunk compression times, excluding loading) ==='
DROP TABLE IF EXISTS ct;
CREATE TEMP TABLE ct (table_name text, chunk_no int, chunk text, range_start timestamptz,
                      range_end timestamptz, rows bigint, load_seconds numeric,
                      compress_seconds numeric, compressed boolean);
\copy ct FROM 'results/compression_timings.csv' WITH (FORMAT csv, HEADER true)
SELECT table_name,
       count(*) FILTER (WHERE compressed) AS chunks_compressed,
       round(sum(load_seconds), 1)        AS total_load_seconds,
       round(sum(compress_seconds), 1)    AS compression_cost_seconds,
       round(avg(compress_seconds), 2)    AS avg_seconds_per_chunk
FROM ct
GROUP BY table_name
ORDER BY table_name;