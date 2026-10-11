-- Section 4.1: two compressed configurations with 1-day chunks
\pset pager off

DROP TABLE IF EXISTS energy_time_compressed;
DROP TABLE IF EXISTS energy_meter_compressed;

CREATE TABLE energy_time_compressed (
    meter_id BIGINT, event_time TIMESTAMPTZ NOT NULL, received_time TIMESTAMPTZ,
    power_kw DOUBLE PRECISION, voltage_v DOUBLE PRECISION, current_a DOUBLE PRECISION,
    frequency_hz DOUBLE PRECISION, energy_kwh DOUBLE PRECISION);
SELECT create_hypertable('energy_time_compressed',
       by_range('event_time', INTERVAL '1 day'), create_default_indexes => FALSE);

CREATE TABLE energy_meter_compressed (
    meter_id BIGINT, event_time TIMESTAMPTZ NOT NULL, received_time TIMESTAMPTZ,
    power_kw DOUBLE PRECISION, voltage_v DOUBLE PRECISION, current_a DOUBLE PRECISION,
    frequency_hz DOUBLE PRECISION, energy_kwh DOUBLE PRECISION);
SELECT create_hypertable('energy_meter_compressed',
       by_range('event_time', INTERVAL '1 day'), create_default_indexes => FALSE);

-- Matching indexes (same as the three Section 3 tables)
CREATE INDEX ix_etc_time       ON energy_time_compressed  USING btree (event_time);
CREATE INDEX ix_etc_meter_time ON energy_time_compressed  USING btree (meter_id, event_time);
CREATE INDEX ix_emc_time       ON energy_meter_compressed USING btree (event_time);
CREATE INDEX ix_emc_meter_time ON energy_meter_compressed USING btree (meter_id, event_time);

-- Compression settings: same ordering; segmentation only on the meter table
ALTER TABLE energy_time_compressed SET (
    timescaledb.compress,
    timescaledb.compress_orderby   = 'event_time DESC',
    timescaledb.compress_segmentby = '');

ALTER TABLE energy_meter_compressed SET (
    timescaledb.compress,
    timescaledb.compress_orderby   = 'event_time DESC',
    timescaledb.compress_segmentby = 'meter_id');

-- Policies: compress chunks whose end is more than 48 hours old, then PAUSE them
SELECT add_compression_policy('energy_time_compressed',  compress_after => INTERVAL '48 hours') AS time_policy_job;
SELECT add_compression_policy('energy_meter_compressed', compress_after => INTERVAL '48 hours') AS meter_policy_job;

SELECT alter_job(job_id, scheduled => false)
FROM timescaledb_information.jobs
WHERE hypertable_name IN ('energy_time_compressed', 'energy_meter_compressed')
  AND proc_name LIKE '%compression%';

\echo '=== Compression settings ==='
SELECT hypertable_name, attname, segmentby_column_index, orderby_column_index, orderby_asc
FROM timescaledb_information.compression_settings
WHERE hypertable_name IN ('energy_time_compressed', 'energy_meter_compressed')
ORDER BY hypertable_name, attname;

\echo '=== Policies (scheduled must be f = paused) ==='
SELECT job_id, hypertable_name, proc_name, scheduled, config
FROM timescaledb_information.jobs
WHERE hypertable_name IN ('energy_time_compressed', 'energy_meter_compressed')
ORDER BY hypertable_name;