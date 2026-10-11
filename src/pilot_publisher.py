"""Section 1.3: MQTT publisher. Takes the first 2,000 dictionaries from the
unchanged generator and publishes each as JSON to energy/meters/{meter_id}
at QoS 1, without retained messages."""
import itertools
import json
import logging
import sys
import threading
from collections import Counter

import paho.mqtt.client as mqtt

import smart_meter_simulator as sim

BROKER_HOST = "localhost"
BROKER_PORT = 1883
PILOT_SIZE = 2000
QOS = 1
LOG_FILE = "results/pilot_publisher.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8"),
              logging.StreamHandler(sys.stdout)])
log = logging.getLogger("publisher")


def main():
    connected = threading.Event()
    puback_lock = threading.Lock()
    puback_count = [0]

    def on_connect(client, userdata, flags, reason_code, properties):
        log.info("Connected to broker %s:%d (%s)", BROKER_HOST, BROKER_PORT, reason_code)
        connected.set()

    def on_publish(client, userdata, mid, reason_code, properties):
        with puback_lock:
            puback_count[0] += 1

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                         client_id="auca-pilot-publisher")
    client.on_connect = on_connect
    client.on_publish = on_publish
    client.max_inflight_messages_set(100)
    client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
    client.loop_start()
    if not connected.wait(timeout=30):
        log.error("Could not connect to the broker within 30 s")
        sys.exit(1)

    taken = 0
    publish_errors = 0
    pairs = Counter()
    infos = []
    for record in itertools.islice(sim.iter_readings(), PILOT_SIZE):
        taken += 1
        pairs[(record["meter_id"], record["event_time"])] += 1
        topic = f"energy/meters/{record['meter_id']}"
        info = client.publish(topic, json.dumps(record), qos=QOS, retain=False)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            publish_errors += 1
            log.error("Publish call failed for %s (rc=%s)", topic, info.rc)
        infos.append(info)
        if taken % 500 == 0:
            log.info("Taken from generator and published: %d", taken)

    for info in infos:
        try:
            info.wait_for_publish(timeout=30)
        except (RuntimeError, ValueError) as exc:
            log.error("Waiting for PUBACK failed for mid %s: %s", info.mid, exc)

    acknowledged = sum(1 for info in infos if info.is_published())
    client.disconnect()
    client.loop_stop()

    duplicate_copies = sum(c - 1 for c in pairs.values() if c > 1)
    log.info("===== PUBLISHER SUMMARY =====")
    log.info("Dictionaries taken from generator : %d", taken)
    log.info("  unique (meter_id, event_time)    : %d", len(pairs))
    log.info("  deliberate duplicate copies      : %d", duplicate_copies)
    log.info("Publish call errors                : %d", publish_errors)
    log.info("Messages acknowledged by broker    : %d", acknowledged)
    log.info("PUBACK callbacks counted           : %d", puback_count[0])


if __name__ == "__main__":
    main()