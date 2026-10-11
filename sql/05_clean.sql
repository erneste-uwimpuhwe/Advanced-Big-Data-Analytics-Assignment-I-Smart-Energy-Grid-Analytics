-- Section 2.3: remove exact duplicate copies from energy_readings (repeatable)
-- Version 2: works on the small set of duplicate pairs to limit memory use.
\timing on
SET work_mem = '64MB';
SET max_parallel_workers_per_gather = 0;

\echo '=== 1. BEFORE cleaning: row count and summed energy ==='
SELECT count(*) AS rows_before,
       round(sum(energy_kwh)::numeric, 6) AS energy_kwh_before
FROM energy_readings;

\echo '=== 2. Find duplicate pairs (same meter_id and event_time) ==='
DROP TABLE IF EXISTS dup_pairs;
CREATE TEMP TABLE dup_pairs AS
SELECT meter_id, event_time, count(*) AS copies
FROM energy_readings
GROUP BY meter_id, event_time
HAVING count(*) > 1;
CREATE INDEX ON dup_pairs (meter_id, event_time);
ANALYZE dup_pairs;

\echo '=== 3. Rows in duplicate pairs, numbered within identical copies ==='
DROP TABLE IF EXISTS dup_rows;
CREATE TEMP TABLE dup_rows AS
SELECT r.tableoid AS tid, r.ctid AS rid,
       r.meter_id, r.event_time, r.received_time, r.power_kw,
       r.voltage_v, r.current_a, r.frequency_hz, r.energy_kwh,
       row_number() OVER (
         PARTITION BY r.meter_id, r.event_time, r.received_time, r.power_kw,
                      r.voltage_v, r.current_a, r.frequency_hz, r.energy_kwh
         ORDER BY r.ctid) AS rn
FROM energy_readings r
JOIN dup_pairs p ON p.meter_id = r.meter_id AND p.event_time = r.event_time;
ANALYZE dup_rows;

\echo '=== 4. Investigation: identical vs conflicting duplicate groups ==='
WITH grp AS (
  SELECT meter_id, event_time, count(*) AS copies,
         count(DISTINCT (received_time, power_kw, voltage_v, current_a,
                         frequency_hz, energy_kwh)) AS distinct_versions
  FROM dup_rows
  GROUP BY meter_id, event_time
)
SELECT count(*)                                      AS duplicate_groups,
       sum(copies - 1)                               AS extra_copies,
       count(*) FILTER (WHERE distinct_versions = 1) AS identical_groups,
       count(*) FILTER (WHERE distinct_versions > 1) AS conflicting_groups,
       max(copies)                                   AS max_copies_per_pair
FROM grp;

\echo '=== 5. Energy held in the extra copies (expected reduction) ==='
SELECT count(*) AS rows_to_delete,
       round(sum(energy_kwh)::numeric, 6) AS energy_in_extra_copies
FROM dup_rows WHERE rn > 1;

\echo '=== 6. Example duplicate groups (all eight fields) ==='
SELECT meter_id, event_time, received_time, power_kw, voltage_v,
       current_a, frequency_hz, energy_kwh
FROM dup_rows
WHERE (meter_id, event_time) IN (SELECT meter_id, event_time FROM dup_pairs
                                 ORDER BY event_time, meter_id LIMIT 2)
ORDER BY event_time, meter_id, rn;

\echo '=== 7. Delete extra identical copies (one transaction, auto rollback on mismatch) ==='
DO $$
DECLARE
  deleted   bigint;
  remaining bigint;
BEGIN
  DELETE FROM energy_readings e
  USING dup_rows d
  WHERE d.rn > 1
    AND e.tableoid = d.tid
    AND e.ctid = d.rid;
  GET DIAGNOSTICS deleted = ROW_COUNT;
  SELECT count(*) INTO remaining FROM energy_readings;
  RAISE NOTICE 'Rows deleted: %, rows remaining: %', deleted, remaining;
  IF remaining <> 10643735 THEN
    RAISE EXCEPTION 'Unexpected remaining count % - transaction rolled back', remaining;
  END IF;
END $$;

\echo '=== 8. AFTER cleaning: row count, summed energy, remaining duplicate pairs ==='
SELECT count(*) AS rows_after,
       round(sum(energy_kwh)::numeric, 6) AS energy_kwh_after,
       (count(*) = 10643735) AS matches_unique_readings
FROM energy_readings;

SELECT count(*) AS duplicate_pairs_remaining
FROM (SELECT 1 FROM energy_readings
      GROUP BY meter_id, event_time HAVING count(*) > 1) x;

\echo '=== 9. Reclaim space and refresh statistics ==='
VACUUM ANALYZE energy_readings;