"""Section 1.2: load meter metadata from the unchanged generator into meters."""
from datetime import datetime

from psycopg2.extras import execute_values

import smart_meter_simulator as sim
from db_config import get_connection


def main():
    start = datetime.now().astimezone()
    print(f"Start (CAT): {start.isoformat(timespec='seconds')}")

    metadata = sim.meter_metadata()
    print(f"Dictionaries returned by meter_metadata(): {len(metadata)}")

    rows = [
        (m["meter_id"], m["region"], m["customer_type"],
         m["base_power_kw"], m["power_factor"])
        for m in metadata
    ]

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE meters")  # makes the script safely repeatable
            execute_values(
                cur,
                "INSERT INTO meters (meter_id, region, customer_type, "
                "base_power_kw, power_factor) VALUES %s",
                rows,
                page_size=1000,
            )
        conn.commit()

        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM meters")
            print(f"Rows in meters table: {cur.fetchone()[0]}")
    finally:
        conn.close()

    end = datetime.now().astimezone()
    print(f"End (CAT): {end.isoformat(timespec='seconds')}")


if __name__ == "__main__":
    main()