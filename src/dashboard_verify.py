"""Section 7.3: compare the numerical data behind every panel of the Raw and
Aggregate dashboards for 22 Sep 00:00 to 29 Sep 00:00 CAT (exclusive),
all regions, meter 1000000000. Exports each panel's data to CSV."""
import os
from datetime import date

from dashboard_queries import PANELS, run_panels

START, END_INCL, METER = date(2026, 9, 22), date(2026, 9, 28), 1000000000
OUT = "results/dashboard_export"
KEYS = {"hourly_region": ["bucket", "region"], "daily_network": ["bucket"],
        "weekly_network": ["bucket"], "meter_daily": ["bucket"], "completeness": ["region"]}
VALUE = {"hourly_region": ("energy_kwh", 0.001, "kWh"),
         "daily_network": ("energy_kwh", 0.001, "kWh"),
         "weekly_network": ("energy_kwh", 0.001, "kWh"),
         "meter_daily": ("energy_kwh", 0.001, "kWh"),
         "completeness": ("completeness_pct", 0.000001, "pct points")}


def keys(df, cols):
    return [tuple(str(v) for v in row) for row in df[cols].itertuples(index=False)]


def main():
    os.makedirs(OUT, exist_ok=True)
    raw, params = run_panels("raw", START, END_INCL, METER)
    agg, _ = run_panels("aggregate", START, END_INCL, METER)
    print(f"Filters: {params['start']} to {params['end']} (exclusive), all regions, meter {METER}\n")
    print(f"{'Panel':<16}{'Raw rows':>9}{'Agg rows':>9}  {'Keys same':<10}{'Counts same':<12}"
          f"{'Max abs diff':>16}  {'Limit':<20}{'Result'}")
    all_ok = True
    for key, _ in PANELS:
        r, _ = raw[key]
        a, _ = agg[key]
        r.to_csv(f"{OUT}/{key}_raw.csv", index=False)
        a.to_csv(f"{OUT}/{key}_aggregate.csv", index=False)
        col, limit, unit = VALUE[key]
        same_keys = len(r) == len(a) and keys(r, KEYS[key]) == keys(a, KEYS[key])
        same_counts = same_keys and r["readings"].tolist() == a["readings"].tolist()
        if key == "completeness" and same_keys:
            same_counts = same_counts and r["planned"].tolist() == a["planned"].tolist()
        max_diff = (r[col].astype(float) - a[col].astype(float)).abs().max() if same_keys else float("nan")
        ok = same_keys and same_counts and max_diff <= limit
        all_ok = all_ok and ok
        print(f"{key:<16}{len(r):>9}{len(a):>9}  {str(same_keys):<10}{str(same_counts):<12}"
              f"{max_diff:>16.3e}  <= {limit:g} {unit:<11}{'PASS' if ok else 'FAIL'}")
    print(f"\nALL FIVE PANELS MATCH: {all_ok}")
    print(f"Panel data exported to {OUT}\\<panel>_raw.csv and <panel>_aggregate.csv")


if __name__ == "__main__":
    main()