-- Section 6.1: view definitions, storage, sample rows, then policies + job status
\pset pager off

\echo '=== 1. View definitions and real-time setting (materialized_only must be t) ==='
SELECT view_name, materialized_only, view_definition
FROM timescaledb_information.continuous_aggregates
WHERE view_name IN ('cagg_15min_region', 'cagg_hour_region', 'cagg_day_meter')
ORDER BY view_name;

\echo '=== 2. Materialized storage (data, index, total) after initial refresh ==='
SELECT ca.view_name,
       pg_size_pretty(s.table_bytes) AS data_size,
       pg_size_pretty(s.index_bytes) AS index_size,
       pg_size_pretty(s.total_bytes) AS total_size,
       round(s.total_bytes / 1048576.0, 2) AS total_mb
FROM timescaledb_information.continuous_aggregates ca,
     LATERAL hypertable_detailed_size(
       format('%I.%I', ca.materialization_hypertable_schema,
                       ca.materialization_hypertable_name)::regclass) s
WHERE ca.view_name IN ('cagg_15min_region', 'cagg_hour_region', 'cagg_day_meter')
ORDER BY ca.view_name;

\echo '=== 3. Sample populated rows ==='
SELECT * FROM cagg_15min_region ORDER BY bucket, region LIMIT 3;
SELECT * FROM cagg_hour_region  ORDER BY bucket, region LIMIT 3;
SELECT * FROM cagg_day_meter    ORDER BY bucket, meter_id LIMIT 3;

\echo '=== 4. Add refresh policies: 3-day lookback, 1-hour end offset, every 15 minutes ==='
SELECT add_continuous_aggregate_policy('cagg_15min_region',
       start_offset => INTERVAL '3 days', end_offset => INTERVAL '1 hour',
       schedule_interval => INTERVAL '15 minutes') AS job_15min;
SELECT add_continuous_aggregate_policy('cagg_hour_region',
       start_offset => INTERVAL '3 days', end_offset => INTERVAL '1 hour',
       schedule_interval => INTERVAL '15 minutes') AS job_hour;
SELECT add_continuous_aggregate_policy('cagg_day_meter',
       start_offset => INTERVAL '3 days', end_offset => INTERVAL '1 hour',
       schedule_interval => INTERVAL '15 minutes') AS job_day;

\echo '=== 5. Policy settings ==='
SELECT j.job_id, ca.view_name, j.schedule_interval, j.scheduled, j.config
FROM timescaledb_information.jobs j
JOIN timescaledb_information.continuous_aggregates ca
  ON ca.materialization_hypertable_name = j.hypertable_name
WHERE j.proc_name = 'policy_refresh_continuous_aggregate'
ORDER BY ca.view_name;

\echo '=== 6. Background job status ==='
SELECT js.job_id, ca.view_name, js.job_status, js.last_run_status,
       js.last_run_started_at, js.next_start, js.total_runs, js.total_failures
FROM timescaledb_information.job_stats js
JOIN timescaledb_information.jobs j USING (job_id)
JOIN timescaledb_information.continuous_aggregates ca
  ON ca.materialization_hypertable_name = j.hypertable_name
WHERE j.proc_name = 'policy_refresh_continuous_aggregate'
ORDER BY ca.view_name;