"""Shared PostgreSQL connection settings.
The password is read from the PGPASSWORD environment variable,
so no secret is stored in the code."""
import os
import psycopg2

DB_SETTINGS = {
    "host": os.environ.get("PGHOST", "localhost"),
    "port": int(os.environ.get("PGPORT", "5432")),
    "dbname": os.environ.get("PGDATABASE", "smart_grid"),
    "user": os.environ.get("PGUSER", "postgres"),
    "password": os.environ.get("PGPASSWORD", "your_password"),
}


def get_connection():
    """Open a connection with the session time zone set to CAT."""
    conn = psycopg2.connect(**DB_SETTINGS)
    with conn.cursor() as cur:
        cur.execute("SET TIME ZONE 'Africa/Kigali'")
    conn.commit()
    return conn