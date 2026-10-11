"""Section 5.1: daily and weekly network energy, top three demand intervals,
and the average daily demand profile. Uses cleaned energy_readings (CAT)."""
import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from db_config import get_connection

warnings.filterwarnings("ignore", message="pandas only supports SQLAlchemy")
OUT = "results/charts"


def query(conn, sql):
    return pd.read_sql_query(sql, conn)


def main():
    conn = get_connection()

    # Daily totals per CAT day (buckets aligned to CAT midnight)
    daily = query(conn, """
        SELECT time_bucket('1 day', event_time, 'Africa/Kigali')::date AS cat_day,
               sum(energy_kwh) AS energy_kwh,
               count(*)        AS readings
        FROM energy_readings
        GROUP BY 1
        ORDER BY 1""")
    daily["weekday"] = pd.to_datetime(daily["cat_day"]).dt.day_name()

    # Four seven-day periods beginning 1, 8, 15 and 22 September (CAT)
    weekly = query(conn, """
        SELECT time_bucket('7 days', event_time,
                           origin => timestamptz '2026-09-01 00:00:00+02')::date AS period_start,
               sum(energy_kwh) AS energy_kwh,
               count(*)        AS readings
        FROM energy_readings
        GROUP BY 1
        ORDER BY 1""")

    # Three highest 15-minute network demand intervals (times returned as CAT text)
    peaks = query(conn, """
        SELECT event_time::text AS event_time_cat,
               sum(power_kw)    AS network_kw,
               count(*)         AS readings
        FROM energy_readings
        GROUP BY event_time
        ORDER BY network_kw DESC, event_time ASC
        LIMIT 3""")

    # Average network demand by time of day, weekdays vs weekends (CAT)
    profile = query(conn, """
        SELECT to_char(event_time, 'HH24:MI') AS time_of_day,
               CASE WHEN extract(isodow FROM event_time) >= 6 THEN 'Weekend'
                    ELSE 'Weekday' END AS day_type,
               avg(network_kw) AS avg_network_kw
        FROM (SELECT event_time, sum(power_kw) AS network_kw
              FROM energy_readings
              GROUP BY event_time) t
        GROUP BY 1, 2
        ORDER BY 1, 2""")
    conn.close()

    pd.set_option("display.width", 160)
    print("=== Daily network energy (CAT days) ===")
    print(daily.to_string(index=False, float_format=lambda v: f"{v:,.1f}"))
    print(f"\nTotal energy: {daily['energy_kwh'].sum():,.3f} kWh")

    print("\n=== Seven-day periods (beginning 1, 8, 15, 22 September) ===")
    print(weekly.to_string(index=False, float_format=lambda v: f"{v:,.1f}"))

    print("\n=== Three highest 15-minute network demand intervals (CAT) ===")
    print(peaks.to_string(index=False, float_format=lambda v: f"{v:,.3f}"))

    # Peak-hour summary from the profile
    for day_type, grp in profile.groupby("day_type"):
        top = grp.loc[grp["avg_network_kw"].idxmax()]
        print(f"{day_type} average profile peaks at {top['time_of_day']} CAT "
              f"({top['avg_network_kw']:,.1f} kW)")

    # Chart 1: daily energy
    fig, ax = plt.subplots(figsize=(12, 5))
    colors = ["tab:orange" if d in ("Saturday", "Sunday") else "tab:blue"
              for d in daily["weekday"]]
    ax.bar(pd.to_datetime(daily["cat_day"]).dt.strftime("%d %b"),
           daily["energy_kwh"], color=colors)
    ax.set_title("Total network energy per CAT day, 1-28 September 2026 (orange = weekend)")
    ax.set_ylabel("Energy (kWh)")
    ax.set_xlabel("CAT day")
    plt.xticks(rotation=60)
    plt.tight_layout()
    plt.savefig(f"{OUT}/5_1_daily_energy.png", dpi=120)
    plt.close(fig)

    # Chart 2: seven-day periods
    fig, ax = plt.subplots(figsize=(8, 5))
    labels = [f"{pd.Timestamp(d):%d %b} - {pd.Timestamp(d) + pd.Timedelta(days=6):%d %b}"
              for d in weekly["period_start"]]
    ax.bar(labels, weekly["energy_kwh"], color="tab:green")
    for i, v in enumerate(weekly["energy_kwh"]):
        ax.text(i, v, f"{v:,.0f}", ha="center", va="bottom")
    ax.set_title("Network energy per seven-day period")
    ax.set_ylabel("Energy (kWh)")
    plt.tight_layout()
    plt.savefig(f"{OUT}/5_1_weekly_energy.png", dpi=120)
    plt.close(fig)

    # Chart 3: average daily demand profile
    fig, ax = plt.subplots(figsize=(12, 5))
    for day_type, grp in profile.groupby("day_type"):
        ax.plot(grp["time_of_day"], grp["avg_network_kw"], label=day_type)
    ax.set_xticks(range(0, 96, 8))
    ax.set_title("Average network demand by time of day (15-minute intervals, CAT)")
    ax.set_ylabel("Network demand (kW)")
    ax.set_xlabel("Time of day (CAT)")
    ax.legend()
    plt.tight_layout()
    plt.savefig(f"{OUT}/5_1_daily_profile.png", dpi=120)
    plt.close(fig)

    print(f"\nCharts saved in {OUT}: 5_1_daily_energy.png, "
          "5_1_weekly_energy.png, 5_1_daily_profile.png")


if __name__ == "__main__":
    main()