"""Sections 3.2 and 4.3: benchmark workloads Q1-Q5 on several hypertables.

For each query and table: 1 warm-up + 5 measured executions (warm cache).
Each execution is timed from statement submission until the last result row
is received by the client (psycopg2 fetchall), with time.perf_counter().

Usage:
  python src\\benchmark.py --label section3 --tables energy_readings energy_readings_3h energy_readings_week
"""
import argparse
import csv
import json
import platform
import socket
import statistics
import sys
import time
from datetime import datetime
from decimal import Decimal

import psycopg2

from db_config import get_connection

QUERIES = {
    "Q1": """
        SELECT time_bucket('1 hour', event_time) AS cat_hour,
               avg(power_kw) AS avg_power_kw,
               count(*)      AS readings
        FROM {t}
        WHERE event_time >= '2026-09-21 00:00:00+02'
          AND event_time <  '2026-09-22 00:00:00+02'
        GROUP BY cat_hour
        ORDER BY cat_hour""",
    "Q2": """
        SELECT event_time, sum(power_kw) AS total_power_kw
        FROM {t}
        WHERE event_time >= '2026-09-22 00:00:00+02'
          AND event_time <  '2026-09-29 00:00:00+02'
        GROUP BY event_time
        ORDER BY total_power_kw DESC, event_time ASC
        LIMIT 10""",
    "Q3": """
        SELECT meter_id, sum(energy_kwh) AS total_energy_kwh
        FROM {t}
        GROUP BY meter_id
        ORDER BY meter_id""",
    "Q4": """
        SELECT sum(energy_kwh) AS energy_kwh,
               avg(power_kw)   AS avg_power_kw,
               max(power_kw)   AS peak_power_kw
        FROM {t}
        WHERE meter_id = 1000000000
          AND event_time >= '2026-09-22 00:00:00+02'
          AND event_time <  '2026-09-29 00:00:00+02'""",
    "Q5": """
        SELECT count(*)        AS row_count,
               sum(energy_kwh) AS total_energy_kwh,
               avg(power_kw)   AS avg_power_kw,
               min(power_kw)   AS min_power_kw,
               max(power_kw)   AS max_power_kw
        FROM {t}""",
}
TOLERANCE = 0.001
MEASURED_RUNS = 5


def now_cat():
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def rows_match(a, b):
    """Compare two result sets: same keys/counts, numbers within TOLERANCE."""
    if len(a) != len(b):
        return False, f"row count {len(a)} vs {len(b)}"
    max_diff = 0.0
    for i, (ra, rb) in enumerate(zip(a, b)):
        for x, y in zip(ra, rb):
            if isinstance(x, (int, float, Decimal)) and not isinstance(x, bool):
                diff = abs(float(x) - float(y))
                max_diff = max(max_diff, diff)
                if diff > TOLERANCE:
                    return False, f"row {i}: {x} vs {y}"
            elif x != y:
                return False, f"row {i}: {x} vs {y}"
    return True, f"max abs diff {max_diff:.3g}"


def run_once(cur, sql):
    start_iso = now_cat()
    t0 = time.perf_counter()
    cur.execute(sql)            # statement submission
    rows = cur.fetchall()       # last result row received
    t1 = time.perf_counter()
    return rows, (t1 - t0) * 1000.0, start_iso, now_cat()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--tables", nargs="+", required=True)
    parser.add_argument("--baseline", default=None,
                        help="table whose results are the reference (default: first)")
    args = parser.parse_args()
    baseline = args.baseline or args.tables[0]

    machine = socket.gethostname()
    client = f"Python {platform.python_version()} + psycopg2 {psycopg2.__version__}"
    timer = "time.perf_counter() (submission to fetchall completion)"

    conn = get_connection()
    conn.autocommit = True
    cur = conn.cursor()

    runs, results, summary = [], {}, []
    session_start_iso = now_cat()
    session_t0 = time.perf_counter()
    print(f"Machine: {machine} | Client: {client} | Timer: {timer}")
    print(f"Session start (CAT): {session_start_iso}")

    for q, template in QUERIES.items():
        for table in args.tables:
            sql = template.format(t=table)
            _, wms, ws, we = run_once(cur, sql)
            runs.append([args.label, q, table, "warm-up", 0, ws, we,
                         round(wms, 3), machine])
            durations = []
            for i in range(1, MEASURED_RUNS + 1):
                rows, ms, s, e = run_once(cur, sql)
                durations.append(ms)
                runs.append([args.label, q, table, "measured", i, s, e,
                             round(ms, 3), machine])
            results[(q, table)] = rows
            med = statistics.median(durations)
            summary.append({"query": q, "table": table,
                            "median_ms": round(med, 3),
                            "min_ms": round(min(durations), 3),
                            "max_ms": round(max(durations), 3),
                            "result_rows": len(rows)})
            print(f"{q} {table:<26} warm-up {wms:9.1f} ms | median {med:9.1f} "
                  f"min {min(durations):9.1f} max {max(durations):9.1f} ms | rows {len(rows)}")

    session_seconds = time.perf_counter() - session_t0
    session_end_iso = now_cat()
    conn.close()

    print("\n=== Result checks against baseline:", baseline, "===")
    all_ok = True
    for row in summary:
        ok, msg = rows_match(results[(row["query"], row["table"])],
                             results[(row["query"], baseline)])
        row["matches_baseline"] = ok
        row["check"] = msg
        all_ok = all_ok and ok
        print(f"{row['query']} {row['table']:<26} match={ok} ({msg})")

    print("\n=== Summary (warm-cache, milliseconds) ===")
    print(f"{'Query':<6}{'Table':<28}{'Median':>11}{'Min':>11}{'Max':>11}")
    for row in summary:
        print(f"{row['query']:<6}{row['table']:<28}{row['median_ms']:>11.1f}"
              f"{row['min_ms']:>11.1f}{row['max_ms']:>11.1f}")
    print(f"\nSession start (CAT): {session_start_iso}")
    print(f"Session end   (CAT): {session_end_iso}")
    print(f"Session seconds (first warm-up submission to last measured result): "
          f"{session_seconds:.1f}")
    print(f"ALL RESULTS MATCH: {all_ok}")

    with open(f"results/bench_{args.label}_runs.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["label", "query", "table", "run_type", "run_no",
                    "start_cat", "end_cat", "duration_ms", "machine"])
        w.writerows(runs)
    with open(f"results/bench_{args.label}_summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0].keys()))
        w.writeheader()
        w.writerows(summary)
    with open(f"results/bench_{args.label}_session.json", "w") as f:
        json.dump({"machine": machine, "client": client, "timer": timer,
                   "session_start_cat": session_start_iso,
                   "session_end_cat": session_end_iso,
                   "session_seconds": round(session_seconds, 3),
                   "all_results_match": all_ok}, f, indent=2)
    print(f"Saved results/bench_{args.label}_runs.csv, _summary.csv, _session.json")


if __name__ == "__main__":
    main()