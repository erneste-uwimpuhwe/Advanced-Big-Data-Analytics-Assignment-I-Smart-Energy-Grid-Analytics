-- Section 3.2: actual execution plan (timing + buffers) for Q1 on table :tbl
\pset pager off
EXPLAIN (ANALYZE, BUFFERS, TIMING, COSTS OFF)
SELECT time_bucket('1 hour', event_time) AS cat_hour,
       avg(power_kw) AS avg_power_kw,
       count(*)      AS readings
FROM :tbl
WHERE event_time >= '2026-09-21 00:00:00+02'
  AND event_time <  '2026-09-22 00:00:00+02'
GROUP BY cat_hour
ORDER BY cat_hour;