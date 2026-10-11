"""Section 6.2: freshness and delayed-arrival test on a separate hypertable
with an hourly continuous aggregate (real-time off, no automatic refresh)."""
from datetime import timedelta

from db_config import get_connection


def show(cur, title, sql, params=None):
    cur.execute(sql, params)
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    print(f"\n--- {title} ---")
    print(" | ".join(cols))
    if not rows:
        print("(no rows: no bucket returned)")
    for r in rows:
        print(" | ".join(str(v) for v in r))


def main():
    conn = get_connection()
    conn.autocommit = True          # refresh_continuous_aggregate cannot run in a transaction
    cur = conn.cursor()

    print("=== Setup: test hypertable and hourly continuous aggregate ===")
    cur.execute("DROP MATERIALIZED VIEW IF EXISTS freshness_hourly CASCADE")
    cur.execute("DROP TABLE IF EXISTS freshness_test CASCADE")
    cur.execute("""CREATE TABLE freshness_test (
                       event_time TIMESTAMPTZ NOT NULL,
                       energy_kwh DOUBLE PRECISION)""")
    cur.execute("SELECT create_hypertable('freshness_test', by_range('event_time', INTERVAL '1 day'))")
    cur.execute("""CREATE MATERIALIZED VIEW freshness_hourly
                   WITH (timescaledb.continuous, timescaledb.materialized_only = true) AS
                   SELECT time_bucket(INTERVAL '1 hour', event_time, 'Africa/Kigali') AS bucket,
                          sum(energy_kwh) AS energy_kwh,
                          count(*)        AS row_count
                   FROM freshness_test
                   GROUP BY 1
                   WITH NO DATA""")
    show(cur, "Real-time aggregation setting (materialized_only = true means real-time OFF)",
         """SELECT view_name, materialized_only FROM timescaledb_information.continuous_aggregates
            WHERE view_name = 'freshness_hourly'""")
    show(cur, "Automatic refresh policies on freshness_hourly (none expected)",
         """SELECT job_id FROM timescaledb_information.jobs
            WHERE proc_name = 'policy_refresh_continuous_aggregate'
              AND hypertable_name IN ('freshness_hourly',
                  (SELECT materialization_hypertable_name FROM timescaledb_information.continuous_aggregates
                   WHERE view_name = 'freshness_hourly'))""")

    # ---- Record the test time, H, and H - 48 h (CAT) ----
    cur.execute("""SELECT now(),
                          date_trunc('hour', now()) - INTERVAL '1 hour'""")
    test_time, _ = cur.fetchone()
    cur.execute("SELECT date_trunc('hour', now())")
    current_hour_start = cur.fetchone()[0]
    H = current_hour_start - timedelta(hours=1)      # most recent COMPLETED CAT hour
    older = H - timedelta(hours=48)
    t_old_1 = older + timedelta(minutes=10)
    t_old_2 = older + timedelta(minutes=25)
    t_h = H + timedelta(minutes=10)

    print("\n=== Recorded times (CAT) ===")
    print(f"Actual test time            : {test_time}")
    print(f"H (most recent completed hr): {H}  to  {H + timedelta(hours=1)}")
    print(f"H - 48 h (older hour)       : {older}  to  {older + timedelta(hours=1)}")
    print(f"Insert 1: 1.0 kWh at {t_old_1}")
    print(f"Insert 2: 0.5 kWh at {t_old_2}")
    print(f"Insert 3: 2.0 kWh at {t_h}")

    agg_sql = """SELECT bucket, energy_kwh, row_count FROM freshness_hourly
                 WHERE bucket IN (%s, %s) ORDER BY bucket"""
    raw_sql = """SELECT time_bucket(INTERVAL '1 hour', event_time, 'Africa/Kigali') AS hour,
                        sum(energy_kwh) AS energy_kwh, count(*) AS row_count
                 FROM freshness_test
                 WHERE event_time >= %s AND event_time < %s
                    OR event_time >= %s AND event_time < %s
                 GROUP BY 1 ORDER BY 1"""
    raw_args = (older, older + timedelta(hours=1), H, H + timedelta(hours=1))

    # ---- Stage 1: insert 1 kWh into the older hour, refresh only that hour ----
    print("\n================ STAGE 1 ================")
    cur.execute("INSERT INTO freshness_test VALUES (%s, 1.0)", (t_old_1,))
    print("Inserted 1.0 kWh into the older hour")
    cur.execute("CALL refresh_continuous_aggregate('freshness_hourly', %s, %s)",
                (older, older + timedelta(hours=1)))
    print("Manually refreshed ONLY the older hour")
    show(cur, "Stage 1 aggregate (real-time OFF)", agg_sql, (older, H))

    # ---- Stage 2: two more inserts, no refresh ----
    print("\n================ STAGE 2 ================")
    cur.execute("INSERT INTO freshness_test VALUES (%s, 0.5)", (t_old_2,))
    cur.execute("INSERT INTO freshness_test VALUES (%s, 2.0)", (t_h,))
    print("Inserted 0.5 kWh into the older hour and 2.0 kWh into hour H (no refresh)")
    show(cur, "Stage 2 raw table (direct query)", raw_sql, raw_args)
    show(cur, "Stage 2 aggregate (real-time OFF, before refresh)", agg_sql, (older, H))

    # ---- Stage 3: enable real-time aggregation, still before refresh ----
    print("\n================ STAGE 3 ================")
    cur.execute("ALTER MATERIALIZED VIEW freshness_hourly SET (timescaledb.materialized_only = false)")
    show(cur, "Real-time setting now", """SELECT view_name, materialized_only
             FROM timescaledb_information.continuous_aggregates WHERE view_name = 'freshness_hourly'""")
    show(cur, "Stage 3 aggregate (real-time ON, still before refresh)", agg_sql, (older, H))

    # ---- Stage 4: manually refresh both complete hours ----
    print("\n================ STAGE 4 ================")
    cur.execute("CALL refresh_continuous_aggregate('freshness_hourly', %s, %s)",
                (older, older + timedelta(hours=1)))
    cur.execute("CALL refresh_continuous_aggregate('freshness_hourly', %s, %s)",
                (H, H + timedelta(hours=1)))
    print("Manually refreshed the older hour and hour H")
    show(cur, "Stage 4 raw table", raw_sql, raw_args)
    show(cur, "Stage 4 aggregate (after refresh of both hours)", agg_sql, (older, H))

    # ---- Which hours could the 6.1 policy refresh right now? ----
    cur.execute("SELECT now() - INTERVAL '3 days', now() - INTERVAL '1 hour'")
    w_start, w_end = cur.fetchone()
    print("\n=== 6.1 policy window at this test time (3-day start offset, 1-hour end offset) ===")
    print(f"Policy refresh window: {w_start}  to  {w_end}")
    print(f"Older hour inside window : {w_start <= older and older + timedelta(hours=1) <= w_end}")
    print(f"Hour H inside window     : {w_start <= H and H + timedelta(hours=1) <= w_end}")
    conn.close()


if __name__ == "__main__":
    main()