"""Section 5.4: detect abnormal consumption in cleaned energy_readings, then
evaluate the flags against anomaly_events() (labels used for evaluation only).

Rule: ratio = power_kw / median power_kw of the same meter, same 15-minute
time-of-day slot and same day type (weekday/weekend).
Flag 'high' if ratio >= 2.0, 'low' if ratio <= 0.4."""
import csv
import time
from collections import defaultdict
from datetime import datetime

import smart_meter_simulator as sim
from db_config import get_connection

HIGH_RATIO = 2.0
LOW_RATIO = 0.4
SLOT = "(extract(hour FROM {t}.event_time) * 4 + extract(minute FROM {t}.event_time) / 15)::int"
WEEKEND = "(extract(isodow FROM {t}.event_time) >= 6)"


def main():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SET work_mem = '64MB'")
    cur.execute("SET max_parallel_workers_per_gather = 0")
    t0 = time.perf_counter()

    print("RULE: ratio = power_kw / median(power_kw) for the same meter, "
          "15-minute slot (CAT) and day type (weekday/weekend)")
    print(f"      flag HIGH if ratio >= {HIGH_RATIO}, LOW if ratio <= {LOW_RATIO}")

    # ---- Step 1: detection on cleaned readings (no labels used) ----
    print("\nBuilding per-meter baselines (median per meter, slot, day type)...")
    cur.execute("DROP TABLE IF EXISTS anomaly_baseline")
    cur.execute(f"""
        CREATE TABLE anomaly_baseline AS
        SELECT r.meter_id,
               {SLOT.format(t='r')}    AS slot,
               {WEEKEND.format(t='r')} AS weekend,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY r.power_kw) AS median_kw,
               count(*) AS samples
        FROM energy_readings r
        GROUP BY 1, 2, 3""")
    cur.execute("CREATE INDEX ON anomaly_baseline (meter_id, slot, weekend)")
    conn.commit()

    print("Applying the rule to all cleaned readings...")
    cur.execute("DROP TABLE IF EXISTS anomaly_flags")
    cur.execute(f"""
        CREATE TABLE anomaly_flags AS
        SELECT r.meter_id, r.event_time, r.power_kw, b.median_kw,
               r.power_kw / b.median_kw AS ratio,
               CASE WHEN r.power_kw / b.median_kw >= %s THEN 'high' ELSE 'low' END AS flag_type
        FROM energy_readings r
        JOIN anomaly_baseline b
          ON b.meter_id = r.meter_id
         AND b.slot     = {SLOT.format(t='r')}
         AND b.weekend  = {WEEKEND.format(t='r')}
        WHERE r.power_kw / b.median_kw >= %s
           OR r.power_kw / b.median_kw <= %s""", (HIGH_RATIO, HIGH_RATIO, LOW_RATIO))
    conn.commit()

    cur.execute("SELECT min(samples), max(samples) FROM anomaly_baseline")
    smin, smax = cur.fetchone()
    cur.execute("SELECT count(*) FROM energy_readings")
    total_obs = cur.fetchone()[0]
    cur.execute("""SELECT meter_id, event_time, power_kw, median_kw, ratio, flag_type
                   FROM anomaly_flags ORDER BY meter_id, event_time""")
    flags = cur.fetchall()
    n_high = sum(1 for f in flags if f[5] == "high")
    print(f"Baseline samples per (meter, slot, day type): {smin} to {smax}")
    print(f"Readings checked: {total_obs:,} | flags: {len(flags)} "
          f"(high {n_high}, low {len(flags) - n_high}) | {time.perf_counter() - t0:.1f} s")

    print("\nSample flagged readings (meter_id, event_time CAT, power_kw, median_kw, ratio, type):")
    for f in flags[:10]:
        print(f"  {f[0]}  {f[1]:%Y-%m-%d %H:%M}  {f[2]:8.3f}  {f[3]:8.3f}  {f[4]:6.2f}  {f[5]}")

    with open("results/anomaly_flags.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["meter_id", "event_time", "power_kw", "median_kw", "ratio", "flag_type"])
        for f in flags:
            w.writerow([f[0], f[1].isoformat(), f[2], f[3], round(f[4], 4), f[5]])

    # ---- Step 2: evaluation against the injected labels ----
    events = sim.anomaly_events()
    by_meter = defaultdict(list)
    for e in events:
        by_meter[e["meter_id"]].append((datetime.fromisoformat(e["start_time"]),
                                        datetime.fromisoformat(e["end_time"])))

    def inside(meter, t):
        return any(s <= t < e for s, e in by_meter.get(meter, []))

    rows, detected, inside_obs = [], 0, 0
    for e in events:
        s = datetime.fromisoformat(e["start_time"])
        en = datetime.fromisoformat(e["end_time"])
        hits = [f for f in flags if f[0] == e["meter_id"] and s <= f[1] < en]
        cur.execute("""SELECT count(*), min(power_kw), max(power_kw)
                       FROM energy_readings
                       WHERE meter_id = %s AND event_time >= %s AND event_time < %s""",
                    (e["meter_id"], s, en))
        obs, pmin, pmax = cur.fetchone()
        inside_obs += obs
        is_det = len(hits) > 0
        detected += is_det
        rows.append([e["meter_id"], e["event_type"], e["start_time"], e["end_time"],
                     obs, len(hits), "DETECTED" if is_det else "MISSED"])
    conn.close()

    false_flags = [f for f in flags if not inside(f[0], f[1])]
    outside_obs = total_obs - inside_obs
    fp_meters = {f[0] for f in false_flags}

    print("\n=== Injected events (labels used only for evaluation) ===")
    print(f"{'meter_id':<12}{'type':<14}{'start (CAT)':<27}{'readings':>9}{'flags':>7}  result")
    for r in rows:
        print(f"{r[0]:<12}{r[1]:<14}{r[2]:<27}{r[4]:>9}{r[5]:>7}  {r[6]}")

    print("\n=== Evaluation summary ===")
    print(f"Detected events : {detected} of {len(events)}")
    print(f"Missed events   : {len(events) - detected} of {len(events)}")
    print(f"False flags     : {len(false_flags)} = "
          f"{100 * len(false_flags) / outside_obs:.6f} % of {outside_obs:,} "
          "observed readings outside injected intervals")
    print(f"Percentage of meters affected by false flags: {len(fp_meters)} / 4000 = "
          f"{100 * len(fp_meters) / 4000:.2f} %")
    if false_flags:
        print("False-flag examples:")
        for f in false_flags[:10]:
            print(f"  {f[0]}  {f[1]:%Y-%m-%d %H:%M}  ratio {f[4]:.2f} ({f[5]})")

    with open("results/anomaly_evaluation.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["meter_id", "event_type", "start_time", "end_time",
                    "observed_readings", "flags_inside", "result"])
        w.writerows(rows)
    print("\nSaved results/anomaly_flags.csv and results/anomaly_evaluation.csv")


if __name__ == "__main__":
    main()