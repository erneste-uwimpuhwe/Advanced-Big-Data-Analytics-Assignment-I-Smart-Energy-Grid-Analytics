"""Section 1.3: MQTT subscriber for energy/meters/# at QoS 1.
Parses each JSON message and inserts its eight fields into energy_live.
Start this program BEFORE the publisher.

Version 2 (fix after run 1 lost 196 messages): on_message only queues the
raw message, so the client acknowledges the broker quickly and the broker's
per-session queue does not overflow. The main thread parses and inserts in
batches."""
import json
import logging
import queue
import sys
import threading
import time

import paho.mqtt.client as mqtt
from psycopg2.extras import execute_values

from db_config import get_connection

BROKER_HOST = "localhost"
BROKER_PORT = 1883
TOPIC = "energy/meters/#"
QOS = 1
IDLE_SECONDS = 15
BATCH_SIZE = 200
LOG_FILE = "results/pilot_subscriber.log"
FIELDS = ("meter_id", "event_time", "received_time", "power_kw",
          "voltage_v", "current_a", "frequency_hz", "energy_kwh")
INSERT_SQL = ("INSERT INTO energy_live (meter_id, event_time, received_time, "
              "power_kw, voltage_v, current_a, frequency_hz, energy_kwh) VALUES %s")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8"),
              logging.StreamHandler(sys.stdout)])
log = logging.getLogger("subscriber")


class Stats:
    received = 0
    redelivered = 0
    topic_mismatch = 0
    parse_errors = 0
    insert_errors = 0
    inserted = 0
    last_message = None


def insert_batch(conn, cur, rows, stats):
    """Insert a batch; if it fails, retry row by row so errors are isolated."""
    try:
        execute_values(cur, INSERT_SQL, rows)
        conn.commit()
        stats.inserted += len(rows)
    except Exception as exc:
        conn.rollback()
        log.error("Batch insert failed (%s); retrying row by row", exc)
        for row in rows:
            try:
                execute_values(cur, INSERT_SQL, [row])
                conn.commit()
                stats.inserted += 1
            except Exception as row_exc:
                conn.rollback()
                stats.insert_errors += 1
                log.error("Insert failed for %s: %s", row[:2], row_exc)


def main():
    stats = Stats()
    subscribed = threading.Event()
    inbox = queue.Queue()

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("TRUNCATE energy_live")
    conn.commit()
    cur.execute("SELECT count(*) FROM energy_live")
    log.info("energy_live rows at start: %d", cur.fetchone()[0])

    def on_connect(client, userdata, flags, reason_code, properties):
        log.info("Connected to broker %s:%d (%s)", BROKER_HOST, BROKER_PORT, reason_code)
        client.subscribe(TOPIC, qos=QOS)

    def on_subscribe(client, userdata, mid, reason_code_list, properties):
        log.info("Subscribed to %s, granted QoS: %s",
                 TOPIC, [str(rc) for rc in reason_code_list])
        subscribed.set()

    def on_message(client, userdata, msg):
        # Keep this fast: just count and queue the message.
        stats.received += 1
        stats.last_message = time.monotonic()
        if msg.dup:
            stats.redelivered += 1
        inbox.put((msg.topic, msg.payload))

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                         client_id="auca-pilot-subscriber", clean_session=True)
    client.on_connect = on_connect
    client.on_subscribe = on_subscribe
    client.on_message = on_message
    client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
    client.loop_start()

    if not subscribed.wait(timeout=30):
        log.error("Could not subscribe within 30 s - is EMQX running?")
        client.loop_stop()
        sys.exit(1)
    log.info("READY - now start the publisher in the other window")

    batch = []
    processed = 0
    while True:
        try:
            topic, payload = inbox.get(timeout=1)
        except queue.Empty:
            if batch:
                insert_batch(conn, cur, batch, stats)
                batch = []
            if (stats.last_message and inbox.empty()
                    and time.monotonic() - stats.last_message > IDLE_SECONDS):
                break
            continue

        processed += 1
        try:
            record = json.loads(payload.decode("utf-8"))
            row = tuple(record[f] for f in FIELDS)
        except Exception as exc:
            stats.parse_errors += 1
            log.error("Parse error on %s: %s payload=%r", topic, exc, payload[:200])
            continue
        if topic != f"energy/meters/{record['meter_id']}":
            stats.topic_mismatch += 1
            log.warning("Topic %s does not match meter_id %s", topic, record["meter_id"])
        batch.append(row)
        if len(batch) >= BATCH_SIZE:
            insert_batch(conn, cur, batch, stats)
            batch = []
        if processed % 500 == 0:
            log.info("Processed %d messages so far", processed)

    client.disconnect()
    client.loop_stop()
    cur.execute("SELECT count(*) FROM energy_live")
    db_rows = cur.fetchone()[0]
    conn.close()

    log.info("===== SUBSCRIBER SUMMARY =====")
    log.info("Messages received by subscriber : %d", stats.received)
    log.info("  of which redelivered (DUP)    : %d", stats.redelivered)
    log.info("  topic/meter_id mismatches     : %d", stats.topic_mismatch)
    log.info("  parse errors                  : %d", stats.parse_errors)
    log.info("  insert errors                 : %d", stats.insert_errors)
    log.info("Rows inserted (committed)       : %d", stats.inserted)
    log.info("Rows in energy_live (query)     : %d", db_rows)


if __name__ == "__main__":
    main()