"""Section 5.3: completeness for the network and each region (28 days), and
the effect of delayed arrivals on the 21 September daily energy total."""
import warnings

import pandas as pd

from db_config import get_connection

warnings.filterwarnings("ignore", message="pandas only supports SQLAlchemy")
INTERVALS = 28 * 96          # planned readings per meter


def main():
    conn = get_connection()

    region = pd.read_sql_query(f"""
        WITH obs AS (SELECT meter_id, count(*) AS observed
                     FROM energy_readings GROUP BY meter_id)
        SELECT m.region,
               count(*)                         AS registered_meters,
               count(*) * {INTERVALS}           AS planned_readings,
               coalesce(sum(o.observed), 0)     AS observed_unique_pairs,
               100.0 * coalesce(sum(o.observed), 0) / (count(*) * {INTERVALS}) AS completeness_pct
        FROM meters m LEFT JOIN obs o USING (meter_id)
        GROUP BY m.region""", conn)
    region["n"] = region["region"].str.split().str[1].astype(int)
    region = region.sort_values("n").drop(columns="n")

    network = pd.DataFrame([{
        "region": "NETWORK",
        "registered_meters": region["registered_meters"].sum(),
        "planned_readings": region["planned_readings"].sum(),
        "observed_unique_pairs": region["observed_unique_pairs"].sum(),
    }])
    network["completeness_pct"] = (100.0 * network["observed_unique_pairs"]
                                   / network["planned_readings"])
    dupes = pd.read_sql_query("""
        SELECT count(*) AS duplicate_pairs FROM (
          SELECT 1 FROM energy_readings GROUP BY meter_id, event_time HAVING count(*) > 1) x""", conn)

    day = pd.read_sql_query("""
        SELECT count(*) FILTER (WHERE received_time <= '2026-09-22 00:00:00+02') AS readings_by_midnight,
               count(*)                                                          AS readings_all_arrivals,
               sum(energy_kwh) FILTER (WHERE received_time <= '2026-09-22 00:00:00+02') AS kwh_by_midnight,
               sum(energy_kwh)                                                   AS kwh_all_arrivals
        FROM energy_readings
        WHERE event_time >= '2026-09-21 00:00:00+02'
          AND event_time <  '2026-09-22 00:00:00+02'""", conn)

    late = pd.read_sql_query("""
        SELECT to_char(event_time, 'HH24:00') AS event_hour_cat,
               count(*)        AS late_readings,
               sum(energy_kwh) AS late_kwh
        FROM energy_readings
        WHERE event_time >= '2026-09-21 00:00:00+02'
          AND event_time <  '2026-09-22 00:00:00+02'
          AND received_time > '2026-09-22 00:00:00+02'
        GROUP BY 1 ORDER BY 1""", conn)
    conn.close()

    pd.set_option("display.width", 160)
    print("=== Completeness over all 28 days (planned = registered meters x 28 x 96) ===")
    table = pd.concat([region, network], ignore_index=True)
    print(table.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    print(f"(Duplicate meter/event_time pairs remaining: {int(dupes.iloc[0, 0])}, "
          "so each row is one unique observed pair)")

    d = day.iloc[0]
    diff = d["kwh_all_arrivals"] - d["kwh_by_midnight"]
    planned_day = 4000 * 96
    print("\n=== 21 September daily energy: arrivals by 00:00 on 22 Sep vs all arrivals ===")
    print(f"Planned readings for the day      : {planned_day:,}")
    print(f"Readings received by 00:00 22 Sep : {int(d['readings_by_midnight']):,}")
    print(f"Readings, all arrivals            : {int(d['readings_all_arrivals']):,}")
    print(f"Missing for the day (never sent)  : {planned_day - int(d['readings_all_arrivals']):,}")
    print(f"Energy by 00:00 22 Sep            : {d['kwh_by_midnight']:,.3f} kWh")
    print(f"Energy, all arrivals (final)      : {d['kwh_all_arrivals']:,.3f} kWh")
    print(f"Difference                        : {diff:,.3f} kWh "
          f"= {100 * diff / d['kwh_all_arrivals']:.4f} % of the final total")

    print("\n=== Late readings (arrived after 00:00 22 Sep) by event hour ===")
    print(late.to_string(index=False, float_format=lambda v: f"{v:,.3f}"))


if __name__ == "__main__":
    main()