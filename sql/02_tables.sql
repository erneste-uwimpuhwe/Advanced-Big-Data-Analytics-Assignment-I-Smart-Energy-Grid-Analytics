-- Section 1.2: reading tables and meters table

DROP TABLE IF EXISTS energy_live;
DROP TABLE IF EXISTS energy_readings;
DROP TABLE IF EXISTS meters;

CREATE TABLE energy_live (
    meter_id       BIGINT,
    event_time     TIMESTAMPTZ,
    received_time  TIMESTAMPTZ,
    power_kw       DOUBLE PRECISION,
    voltage_v      DOUBLE PRECISION,
    current_a      DOUBLE PRECISION,
    frequency_hz   DOUBLE PRECISION,
    energy_kwh     DOUBLE PRECISION
);

CREATE TABLE energy_readings (
    meter_id       BIGINT,
    event_time     TIMESTAMPTZ NOT NULL,
    received_time  TIMESTAMPTZ,
    power_kw       DOUBLE PRECISION,
    voltage_v      DOUBLE PRECISION,
    current_a      DOUBLE PRECISION,
    frequency_hz   DOUBLE PRECISION,
    energy_kwh     DOUBLE PRECISION
);

SELECT create_hypertable(
    'energy_readings',
    by_range('event_time', INTERVAL '1 day'),
    create_default_indexes => FALSE
);

CREATE TABLE meters (
    meter_id       BIGINT PRIMARY KEY,
    region         TEXT,
    customer_type  TEXT,
    base_power_kw  DOUBLE PRECISION,
    power_factor   DOUBLE PRECISION
);