"""Section 2.1: capture the complete generator stream to CSV in batches,
then bulk-load the CSV into the empty energy_readings hypertable with COPY.

Usage:
  python src\\capture_and_load.py              (generate CSV, then load)
  python src\\capture_and_load.py --load-only  (reuse existing CSV, load only)
"""
import argparse
import csv
import json
import logging
import os
import sys
import time
from datetime import datetime

import smart_meter_simulator as sim
from db_config import get_connection

CSV_PATH = r"D:\auca_a1\data\energy_readings_full.csv"
TIMINGS_PATH = "results/load_timings.json"
LOG_FILE = "results/full_load.log"
BATCH_SIZE = 100_000
PROGRESS_EVERY = 1_000_000
FIELDS = ("meter_id", "event_time", "received_time", "power_kw",
          "voltage_v", "current_a", "frequency_hz", "energy_kwh")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_FILE,mode="a", encoding="utf-8"),
              logging.StreamHandler(sys.stdout)])
log = logging.getLogger("full_load")


def now_cat():
    return datetime.now().astimezone().isoformat(timespec="seconds")


class ProgressReader:
    """Wraps the CSV file so COPY progress can be shown while loading."""

    def __init__(self, f, total_bytes):
        self.f = f
        self.total = total_bytes
        self.done = 0
        self.next_report = 0.10

    def read(self, size=-1):
        chunk = self.f.read(size)
        self.done += len(chunk)
        if self.total and self.done / self.total >= self.next_report:
            log.info("COPY progress: %3.0f%% of CSV sent to PostgreSQL",
                     100 * self.done / self.total)
            self.next_report += 0.10
        return chunk

    def readline(self, size=-1):
        line = self.f.readline(size)
        self.done += len(line)
        return line


def generate_csv():
    log.info("PHASE 1: capture generator stream to CSV (%s)", CSV_PATH)
    start_iso = now_cat()
    t0 = time.perf_counter()
    consumed = 0
    batch = []
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(FIELDS)
        for record in sim.iter_readings():          # fresh iterator
            batch.append([record[k] for k in FIELDS])
            consumed += 1
            if len(batch) >= BATCH_SIZE:
                writer.writerows(batch)
                batch.clear()
            if consumed % PROGRESS_EVERY == 0:
                elapsed = time.perf_counter() - t0
                log.info("Consumed %10d dictionaries | %7.1f s | %8.0f rows/s",
                         consumed, elapsed, consumed / elapsed)
        if batch:
            writer.writerows(batch)
    t1 = time.perf_counter()
    end_iso = now_cat()
    log.info("Generation finished: %d dictionaries consumed in %.1f s",
             consumed, t1 - t0)
    return {"consumed": consumed, "gen_start_cat": start_iso,
            "gen_end_cat": end_iso, "gen_seconds": round(t1 - t0, 3),
            "t0": t0}


def count_csv_rows():
    t0 = time.perf_counter()
    newlines = 0
    with open(CSV_PATH, "rb") as f:
        for block in iter(lambda: f.read(1 << 24), b""):
            newlines += block.count(b"\n")
    rows = newlines - 1                      # minus the header line
    log.info("CSV data rows (excluding header): %d (counted in %.1f s)",
             rows, time.perf_counter() - t0)
    return rows


def load_csv():
    log.info("PHASE 2: load CSV into energy_readings with COPY")
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM energy_readings")
    before = cur.fetchone()[0]
    log.info("energy_readings rows before load: %d", before)
    if before != 0:
        log.error("energy_readings is not empty - aborting. TRUNCATE it first.")
        sys.exit(1)

    total_bytes = os.path.getsize(CSV_PATH)
    log.info("CSV size: %.1f MB", total_bytes / 1024 / 1024)
    copy_sql = (f"COPY energy_readings ({', '.join(FIELDS)}) "
                "FROM STDIN WITH (FORMAT csv, HEADER true)")

    load_start_iso = now_cat()
    t_load = time.perf_counter()               # first database write starts here
    with open(CSV_PATH, "rb") as f:
        cur.copy_expert(copy_sql, ProgressReader(f, total_bytes), size=1 << 20)
    conn.commit()                              # final commit
    t_commit = time.perf_counter()
    commit_iso = now_cat()

    cur.execute("SELECT count(*) FROM energy_readings")
    db_rows = cur.fetchone()[0]
    conn.close()
    log.info("COPY committed in %.1f s; rows in energy_readings: %d",
             t_commit - t_load, db_rows)
    return {"db_rows": db_rows, "load_start_cat": load_start_iso,
            "final_commit_cat": commit_iso,
            "load_seconds": round(t_commit - t_load, 3),
            "t_commit": t_commit, "csv_bytes": total_bytes}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--load-only", action="store_true",
                        help="skip generation and load the existing CSV")
    args = parser.parse_args()

    info = sim.dataset_info()
    expected = info["expected_counts"]
    log.info("=" * 60)
    log.info("dataset_info(): generator %s, %d meters, %d days, %s to %s (exclusive)",
             info["generator_version"], info["meters"], info["days"],
             info["start_inclusive"], info["end_exclusive"])
    log.info("planned_readings: %d", info["planned_readings"])
    for key, value in expected.items():
        log.info("expected_counts.%s: %d", key, value)

    result = {"route": "CSV file + PostgreSQL COPY",
              "expected_counts": expected,
              "planned_readings": info["planned_readings"]}

    if not args.load_only:
        gen = generate_csv()
        result.update({k: v for k, v in gen.items() if k != "t0"})
    csv_rows = count_csv_rows()
    load = load_csv()
    result.update({k: v for k, v in load.items() if k != "t_commit"})
    result["csv_rows"] = csv_rows
    if not args.load_only:
        result["total_elapsed_seconds"] = round(load["t_commit"] - gen["t0"], 3)

    emitted = expected["emitted_readings"]
    log.info("===== FULL LOAD SUMMARY =====")
    log.info("Route                              : %s", result["route"])
    if not args.load_only:
        log.info("Dictionaries consumed (generator)  : %d", result["consumed"])
    log.info("CSV data rows                      : %d", csv_rows)
    log.info("Committed rows in energy_readings  : %d", load["db_rows"])
    log.info("expected_counts.emitted_readings   : %d", emitted)
    checks = [csv_rows == emitted, load["db_rows"] == emitted]
    if not args.load_only:
        checks.append(result["consumed"] == emitted)
        log.info("CSV generation seconds             : %.1f", result["gen_seconds"])
    log.info("Database load seconds (COPY->commit): %.1f", load["load_seconds"])
    if not args.load_only:
        log.info("Total elapsed seconds (gen start -> final commit): %.1f",
                 result["total_elapsed_seconds"])
    log.info("ALL COUNTS AGREE                   : %s", all(checks))

    with open(TIMINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    log.info("Timings saved to %s", TIMINGS_PATH)


if __name__ == "__main__":
    main()