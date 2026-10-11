"""Section 7.4: median / min / max per panel and for the whole dashboard,
per mode, from the latest complete benchmark (1 warm-up + 10 measured)."""
import pandas as pd

CSV = "results/dashboard_timings.csv"
PANELS = ["hourly_region", "daily_network", "weekly_network", "meter_daily", "completeness"]
CAGG = {"storage_mb": 4.18 + 1.26 + 12.59, "initial_refresh_s": 102.7 + 143.7 + 89.3}


def main():
    df = pd.read_csv(CSV)
    rows, med = [], {}
    for mode in ("raw", "aggregate"):
        m = df[(df["mode"] == mode) & (df["run_type"] == "measured")]
        complete = m.groupby("bench_id").size()
        complete = complete[complete == 10]
        if complete.empty:
            print(f"No complete benchmark found for {mode}")
            continue
        bench_id = sorted(complete.index)[-1]
        b = m[m["bench_id"] == bench_id]
        print(f"{mode.upper()}: benchmark {bench_id}, {len(b)} measured refreshes, "
              f"{b['start_cat'].min()} to {b['end_cat'].max()}, machine {b['machine'].iloc[0]}")
        for col in [f"{p}_ms" for p in PANELS] + ["dashboard_ms"]:
            s = b[col]
            rows.append({"mode": mode, "measure": col.replace("_ms", ""),
                         "median_ms": round(s.median(), 1), "min_ms": round(s.min(), 1),
                         "max_ms": round(s.max(), 1)})
            med[(mode, col)] = s.median()

    out = pd.DataFrame(rows)
    print("\n" + out.to_string(index=False))
    out.to_csv("results/dashboard_timing_summary.csv", index=False)

    if len(med) == 12:
        print("\nRaw median / Aggregate median (speed-up factor):")
        for col in [f"{p}_ms" for p in PANELS] + ["dashboard_ms"]:
            r, a = med[("raw", col)], med[("aggregate", col)]
            print(f"  {col.replace('_ms', ''):<15} {r:9.1f} ms -> {a:8.1f} ms   x{r / a:,.1f}")
    print(f"\nAggregate cost (Section 6.1): storage {CAGG['storage_mb']:.2f} MB, "
          f"initial refresh {CAGG['initial_refresh_s']:.1f} s")
    print("Tools: panel queries timed with Python time.perf_counter() on the Dash server; "
          "whole dashboard timed in the browser with performance.now() "
          "(refresh request until all five panels painted). Saved results/dashboard_timing_summary.csv")


if __name__ == "__main__":
    main()