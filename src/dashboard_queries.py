"""Section 7: panel queries for the Raw and Aggregate dashboards.
Raw mode reads energy_readings (joined to meters where needed).
Aggregate mode reads the continuous aggregates; it queries meters only for
region labels and registered meter counts. No query-result caching is used."""
import time
from datetime import date, timedelta

import pandas as pd
from psycopg2 import pool

from db_config import DB_SETTINGS

PANELS = [
    ("hourly_region",  "Hourly regional energy (kWh)"),
    ("daily_network",  "Daily network energy (kWh)"),
    ("weekly_network", "Network energy per seven-day period (kWh)"),
    ("meter_daily",    "Daily energy for selected meter (kWh)"),
    ("completeness",   "Completeness by region (%)"),
]
RANGE = "{t} >= %(start)s AND {t} < %(end)s"

SQL = {
    "raw": {
        "hourly_region": f"""
            SELECT time_bucket('1 hour', e.event_time, 'Africa/Kigali') AS bucket, m.region,
                   sum(e.energy_kwh) AS energy_kwh, count(*) AS readings
            FROM energy_readings e JOIN meters m ON m.meter_id = e.meter_id
            WHERE {RANGE.format(t='e.event_time')}
            GROUP BY 1, 2
            ORDER BY 1, split_part(m.region, ' ', 2)::int""",
        "daily_network": f"""
            SELECT time_bucket('1 day', event_time, 'Africa/Kigali') AS bucket,
                   sum(energy_kwh) AS energy_kwh, count(*) AS readings
            FROM energy_readings
            WHERE {RANGE.format(t='event_time')}
            GROUP BY 1 ORDER BY 1""",
        "weekly_network": f"""
            SELECT time_bucket('7 days', event_time,
                               origin => timestamptz '2026-09-01 00:00:00+02') AS bucket,
                   sum(energy_kwh) AS energy_kwh, count(*) AS readings
            FROM energy_readings
            WHERE {RANGE.format(t='event_time')}
            GROUP BY 1 ORDER BY 1""",
        "meter_daily": f"""
            SELECT time_bucket('1 day', event_time, 'Africa/Kigali') AS bucket,
                   sum(energy_kwh) AS energy_kwh, count(*) AS readings
            FROM energy_readings
            WHERE meter_id = %(meter)s AND {RANGE.format(t='event_time')}
            GROUP BY 1 ORDER BY 1""",
        "completeness": f"""
            WITH reg AS (SELECT region, count(*) AS registered FROM meters GROUP BY region),
                 obs AS (SELECT m.region, count(*) AS observed
                         FROM energy_readings e JOIN meters m ON m.meter_id = e.meter_id
                         WHERE {RANGE.format(t='e.event_time')}
                         GROUP BY m.region)
            SELECT reg.region, reg.registered AS registered_meters,
                   coalesce(obs.observed, 0)::bigint AS readings,
                   reg.registered * %(intervals)s AS planned,
                   (100.0 * coalesce(obs.observed, 0) / (reg.registered * %(intervals)s))::double precision
                       AS completeness_pct
            FROM reg LEFT JOIN obs USING (region)
            ORDER BY split_part(reg.region, ' ', 2)::int""",
    },
    "aggregate": {
        "hourly_region": f"""
            SELECT bucket, region, sum_energy_kwh AS energy_kwh, reading_count AS readings
            FROM cagg_hour_region
            WHERE {RANGE.format(t='bucket')}
            ORDER BY bucket, split_part(region, ' ', 2)::int""",
        "daily_network": f"""
            SELECT time_bucket('1 day', bucket, 'Africa/Kigali') AS bucket,
                   sum(sum_energy_kwh) AS energy_kwh, sum(reading_count)::bigint AS readings
            FROM cagg_15min_region
            WHERE {RANGE.format(t='bucket')}
            GROUP BY 1 ORDER BY 1""",
        "weekly_network": f"""
            SELECT time_bucket('7 days', bucket,
                               origin => timestamptz '2026-09-01 00:00:00+02') AS bucket,
                   sum(sum_energy_kwh) AS energy_kwh, sum(reading_count)::bigint AS readings
            FROM cagg_15min_region
            WHERE {RANGE.format(t='bucket')}
            GROUP BY 1 ORDER BY 1""",
        "meter_daily": f"""
            SELECT bucket, sum_energy_kwh AS energy_kwh, reading_count AS readings
            FROM cagg_day_meter
            WHERE meter_id = %(meter)s AND {RANGE.format(t='bucket')}
            ORDER BY bucket""",
        "completeness": f"""
            WITH reg AS (SELECT region, count(*) AS registered FROM meters GROUP BY region),
                 obs AS (SELECT region, sum(reading_count) AS observed
                         FROM cagg_15min_region
                         WHERE {RANGE.format(t='bucket')}
                         GROUP BY region)
            SELECT reg.region, reg.registered AS registered_meters,
                   coalesce(obs.observed, 0)::bigint AS readings,
                   reg.registered * %(intervals)s AS planned,
                   (100.0 * coalesce(obs.observed, 0) / (reg.registered * %(intervals)s))::double precision
                       AS completeness_pct
            FROM reg LEFT JOIN obs USING (region)
            ORDER BY split_part(reg.region, ' ', 2)::int""",
    },
}

_pool = None


def get_pool():
    global _pool
    if _pool is None:
        _pool = pool.ThreadedConnectionPool(
            1, 4, options="-c TimeZone=Africa/Kigali", **DB_SETTINGS)
    return _pool


def make_params(start_day: date, end_day_inclusive: date, meter: int):
    """Whole CAT days: start 00:00 CAT to the day after end_day 00:00 CAT (exclusive)."""
    end_excl = end_day_inclusive + timedelta(days=1)
    days = (end_excl - start_day).days
    return {"start": f"{start_day} 00:00:00+02", "end": f"{end_excl} 00:00:00+02",
            "meter": int(meter), "intervals": days * 96, "days": days}


def run_panels(mode, start_day, end_day_inclusive, meter):
    """Run the five panel queries sequentially; return {panel: (DataFrame, ms)}."""
    params = make_params(start_day, end_day_inclusive, meter)
    p = get_pool()
    conn = p.getconn()
    results = {}
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            for key, _ in PANELS:
                t0 = time.perf_counter()
                cur.execute(SQL[mode][key], params)
                rows = cur.fetchall()
                ms = (time.perf_counter() - t0) * 1000.0
                cols = [d[0] for d in cur.description]
                results[key] = (pd.DataFrame(rows, columns=cols), ms)
    finally:
        p.putconn(conn)
    return results, params


if __name__ == "__main__":
    for mode in ("raw", "aggregate"):
        print("=" * 30, mode.upper(), "dashboard panel queries", "=" * 30)
        for key, title in PANELS:
            print(f"\n-- {title}")
            print(SQL[mode][key].strip())
        print()