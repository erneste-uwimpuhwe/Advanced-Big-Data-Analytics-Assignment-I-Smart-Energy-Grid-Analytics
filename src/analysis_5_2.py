"""Section 5.2: energy by region and by customer type, normalised by the
group's registered meter count. Uses cleaned energy_readings joined to meters."""
import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from db_config import get_connection

warnings.filterwarnings("ignore", message="pandas only supports SQLAlchemy")
OUT = "results/charts"

ENERGY_PER_METER = """
    WITH e AS (SELECT meter_id, sum(energy_kwh) AS kwh
               FROM energy_readings
               GROUP BY meter_id)
    SELECT m.{col}                AS grp,
           count(*)               AS registered_meters,
           sum(e.kwh)             AS total_energy_kwh,
           sum(e.kwh) / count(*)  AS energy_per_meter_kwh
    FROM meters m
    LEFT JOIN e ON e.meter_id = m.meter_id
    GROUP BY m.{col}"""


def main():
    conn = get_connection()

    region = pd.read_sql_query(ENERGY_PER_METER.format(col="region"), conn)
    region["n"] = region["grp"].str.split().str[1].astype(int)
    region = region.sort_values("n").drop(columns="n")

    ctype = pd.read_sql_query(ENERGY_PER_METER.format(col="customer_type"), conn)
    ctype = ctype.sort_values("energy_per_meter_kwh", ascending=False)

    mix = pd.read_sql_query("""
        SELECT region,
               count(*) FILTER (WHERE customer_type = 'residential') AS residential,
               count(*) FILTER (WHERE customer_type = 'commercial')  AS commercial,
               count(*) FILTER (WHERE customer_type = 'industrial')  AS industrial
        FROM meters
        GROUP BY region""", conn)
    mix["n"] = mix["region"].str.split().str[1].astype(int)
    mix = mix.sort_values("n").drop(columns="n")
    conn.close()

    fmt = lambda v: f"{v:,.1f}"
    pd.set_option("display.width", 160)

    print("=== Energy by region (all 28 days) ===")
    print(region.to_string(index=False, float_format=fmt))
    lo = region["energy_per_meter_kwh"].min()
    hi = region["energy_per_meter_kwh"].max()
    print(f"Region per-meter range: {lo:,.1f} to {hi:,.1f} kWh (max/min = {hi / lo:.3f})")

    print("\n=== Energy by customer type (all 28 days) ===")
    print(ctype.to_string(index=False, float_format=fmt))

    print("\n=== Customer mix per region (explains regional differences) ===")
    print(mix.to_string(index=False))

    print(f"\nCheck: total energy = {region['total_energy_kwh'].sum():,.3f} kWh, "
          f"meters = {region['registered_meters'].sum()}")

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    axes[0].bar(region["grp"], region["energy_per_meter_kwh"], color="tab:blue")
    axes[0].set_title("Energy per registered meter by region (28 days)")
    axes[0].set_ylabel("kWh per meter")
    axes[0].tick_params(axis="x", rotation=45)
    axes[1].bar(ctype["grp"], ctype["energy_per_meter_kwh"], color="tab:purple")
    axes[1].set_title("Energy per registered meter by customer type (28 days)")
    axes[1].set_ylabel("kWh per meter")
    plt.tight_layout()
    plt.savefig(f"{OUT}/5_2_energy_per_meter.png", dpi=120)
    plt.close(fig)
    print(f"Chart saved: {OUT}/5_2_energy_per_meter.png")


if __name__ == "__main__":
    main()