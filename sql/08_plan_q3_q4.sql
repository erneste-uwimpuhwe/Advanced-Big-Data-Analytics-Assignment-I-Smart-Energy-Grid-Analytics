\pset pager off
\echo '===== Q3 on' :tbl '====='
EXPLAIN (ANALYZE, BUFFERS, TIMING, COSTS OFF)
SELECT meter_id, sum(energy_kwh) FROM :tbl GROUP BY meter_id ORDER BY meter_id;
\echo '===== Q4 on' :tbl '====='
EXPLAIN (ANALYZE, BUFFERS, TIMING, COSTS OFF)
SELECT sum(energy_kwh), avg(power_kw), max(power_kw) FROM :tbl
WHERE meter_id = 1000000000
  AND event_time >= '2026-09-22 00:00:00+02'
  AND event_time <  '2026-09-29 00:00:00+02';