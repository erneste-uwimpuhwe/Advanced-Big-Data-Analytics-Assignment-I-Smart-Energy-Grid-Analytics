"""Section 4.1: copy the cleaned data into the two compressed hypertables one
chunk at a time. After each chunk is fully loaded, compress it manually if its
end precedes the cutoff (experiment start - 48 h). Loading and compression are
timed separately. The same cutoff is used for both tables."""
import csv
import sys
import time

from db_config import get_connection

SOURCE = "energy_readings"                      # cleaned 1-day hypertable
TARGETS = ["energy_time_compressed", "energy_meter_compressed"]
OUT_CSV = "results/compression_timings.csv"


def main():
    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()

    # One cutoff for the whole experiment, stored in the database
    cur.execute("""CREATE TABLE IF NOT EXISTS compression_experiment (
                       experiment_start TIMESTAMPTZ, cutoff TIMESTAMPTZ)""")
    cur.execute("TRUNCATE compression_experiment")
    cur.execute("""INSERT INTO compression_experiment
                   SELECT now(), now() - INTERVAL '48 hours'
                   RETURNING experiment_start, cutoff""")
    start, cutoff = cur.fetchone()
    conn.commit()
    print(f"Experiment start (CAT): {start}")
    print(f"Cutoff = start - 48 h : {cutoff}")

    for t in TARGETS:
        cur.execute(f"SELECT count(*) FROM {t}")
        if cur.fetchone()[0] != 0:
            print(f"{t} is not empty - run sql\\09_compression_setup.sql again first.")
            sys.exit(1)

    cur.execute("""SELECT range_start, range_end FROM timescaledb_information.chunks
                   WHERE hypertable_name = %s ORDER BY range_start""", (SOURCE,))
    ranges = cur.fetchall()
    print(f"Source chunks to copy: {len(ranges)}")

    rows_out = []
    for table in TARGETS:
        print(f"\n=== {table} ===")
        total_load = total_comp = 0.0
        for i, (r_start, r_end) in enumerate(ranges, 1):
            t0 = time.perf_counter()
            cur.execute(f"""INSERT INTO {table}
                            SELECT * FROM {SOURCE}
                            WHERE event_time >= %s AND event_time < %s
                            ORDER BY event_time""", (r_start, r_end))
            loaded = cur.rowcount
            conn.commit()
            load_s = time.perf_counter() - t0
            total_load += load_s

            cur.execute("""SELECT format('%%I.%%I', chunk_schema, chunk_name), range_end
                           FROM timescaledb_information.chunks
                           WHERE hypertable_name = %s AND range_start = %s""",
                        (table, r_start))
            chunk, chunk_end = cur.fetchone()

            comp_s = None
            if chunk_end < cutoff:
                t1 = time.perf_counter()
                cur.execute("SELECT compress_chunk(%s)", (chunk,))
                conn.commit()
                comp_s = time.perf_counter() - t1
                total_comp += comp_s

            rows_out.append([table, i, chunk, r_start, r_end, loaded,
                             round(load_s, 3),
                             "" if comp_s is None else round(comp_s, 3),
                             comp_s is not None])
            status = f"compressed in {comp_s:6.2f} s" if comp_s is not None else "NOT compressed (after cutoff)"
            print(f"{i:2d} {chunk:<45} rows {loaded:7d} | load {load_s:6.2f} s | {status}")

        print(f"TOTAL {table}: load {total_load:.1f} s, compression {total_comp:.1f} s")

    with open(OUT_CSV, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["table", "chunk_no", "chunk", "range_start", "range_end", "rows",
                    "load_seconds", "compress_seconds", "compressed"])
        w.writerows(rows_out)
    print(f"\nSaved {OUT_CSV}")
    conn.close()


if __name__ == "__main__":
    main()