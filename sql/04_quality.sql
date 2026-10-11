-- Section 2.2: data quality diagnostics on energy_readings BEFORE cleaning
\timing on
SET work_mem = '256MB';

-- One row per observed unique (meter_id, event_time) pair, with copy count
DROP TABLE IF EXISTS q_unique;
CREATE TEMP TABLE q_unique AS
SELECT meter_id, event_time,
       min(received_time) AS received_time,
       count(*)           AS copies
FROM energy_readings
GROUP BY meter_id, event_time;
ANALYZE q_unique;

\echo '=== 1. Measured counts (unique, extra copies, delayed) ==='
SELECT (SELECT count(*) FROM energy_readings)                        AS emitted_rows,
       count(*)                                                      AS unique_pairs,
       sum(copies - 1)                                               AS extra_copies,
       count(*) FILTER (WHERE received_time > event_time + interval '15 minutes') AS delayed_unique,
       count(*) FILTER (WHERE received_time = event_time + interval '15 minutes') AS on_time_unique
FROM q_unique;

\echo '=== 2. Delay range of delayed unique readings (expected 30 to 180 minutes) ==='
SELECT min(received_time - event_time) AS min_delay,
       max(received_time - event_time) AS max_delay
FROM q_unique
WHERE received_time > event_time + interval '15 minutes';

\echo '=== 3. Missing pairs counted directly from the planned grid ==='
SELECT count(*) AS missing_pairs_direct
FROM meters m
CROSS JOIN generate_series(timestamptz '2026-09-01 00:00:00+02',
                           timestamptz '2026-09-28 23:45:00+02',
                           interval '15 minutes') AS g(event_time)
WHERE NOT EXISTS (SELECT 1 FROM q_unique u
                  WHERE u.meter_id = m.meter_id AND u.event_time = g.event_time);

\echo '=== 4. Percentages and consistency checks ==='
WITH m AS (
  SELECT 10752000::numeric                              AS planned,
         (SELECT count(*) FROM energy_readings)::numeric AS emitted,
         count(*)::numeric                              AS uniq,
         sum(copies - 1)::numeric                       AS extra,
         (count(*) FILTER (WHERE received_time > event_time + interval '15 minutes'))::numeric AS delayed
  FROM q_unique
)
SELECT planned,
       planned - uniq                              AS missing,
       round(100 * (planned - uniq) / planned, 4)  AS missing_pct,
       round(100 * extra / uniq, 4)                AS duplicate_pct,
       round(100 * delayed / uniq, 4)              AS delayed_pct,
       round(100 * uniq / planned, 4)              AS completeness_pct,
       (uniq + extra = emitted)                    AS unique_plus_extra_equals_emitted,
       (planned - uniq = 108265)                   AS planned_minus_unique_equals_missing
FROM m;

\echo '=== 5. Measured vs reference counts ==='
WITH meas AS (
  SELECT (SELECT count(*) FROM energy_readings) AS emitted,
         count(*)                               AS uniq,
         sum(copies - 1)                        AS extra,
         count(*) FILTER (WHERE received_time > event_time + interval '15 minutes') AS delayed
  FROM q_unique
)
SELECT e.entry, e.expected, e.measured, (e.expected = e.measured) AS matches
FROM meas, LATERAL (VALUES
  ('planned_readings',        10752000::bigint, 10752000::bigint),
  ('emitted_readings',        10696848, meas.emitted),
  ('unique_readings',         10643735, meas.uniq),
  ('duplicate_readings',      53113,    meas.extra),
  ('delayed_unique_readings', 213090,   meas.delayed),
  ('missing_readings',        108265,   10752000 - meas.uniq)
) AS e(entry, expected, measured);

\echo '=== 6. Five meters with the most missing readings (2,688 planned each) ==='
SELECT m.meter_id, m.region, m.customer_type,
       2688 - count(u.event_time) AS missing_readings
FROM meters m
LEFT JOIN q_unique u ON u.meter_id = m.meter_id
GROUP BY m.meter_id, m.region, m.customer_type
ORDER BY missing_readings DESC, m.meter_id
LIMIT 5;