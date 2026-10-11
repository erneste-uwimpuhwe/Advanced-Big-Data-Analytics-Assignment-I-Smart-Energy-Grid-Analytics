-- Section 2.1 item 5: checks after the full load (before cleaning)
ANALYZE energy_readings;

SELECT count(*) AS total_rows,
       count(DISTINCT meter_id) AS distinct_meters,
       min(event_time) AS earliest_event_time,
       max(event_time) AS latest_event_time
FROM energy_readings;

SELECT count(*) AS chunk_count FROM show_chunks('energy_readings');

SELECT pg_size_pretty(table_bytes)  AS table_data,
       pg_size_pretty(index_bytes)  AS indexes,
       pg_size_pretty(toast_bytes)  AS toast,
       pg_size_pretty(total_bytes)  AS total,
       round(table_bytes / 1024.0 / 1024, 1) AS data_mb,
       round(index_bytes / 1024.0 / 1024, 1) AS index_mb,
       round(total_bytes / 1024.0 / 1024, 1) AS total_mb
FROM hypertable_detailed_size('energy_readings');