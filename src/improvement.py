"""Section 4.3: percentage improvement of compressed tables over the
uncompressed baseline with the same chunk interval (energy_readings, 1 day).
improvement = 100 * (baseline median - compressed median) / baseline median"""
import csv

BASELINE = "energy_readings"
COMPRESSED = ["energy_time_compressed", "energy_meter_compressed"]

with open("results/bench_section4_summary.csv", newline="") as f:
    rows = list(csv.DictReader(f))
median = {(r["query"], r["table"]): float(r["median_ms"]) for r in rows}

lines = ["Query | Baseline median (ms) | time_compressed (ms) | improvement % | "
         "meter_compressed (ms) | improvement %"]
for q in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
    b = median[(q, BASELINE)]
    parts = [q, f"{b:.1f}"]
    for t in COMPRESSED:
        c = median[(q, t)]
        parts += [f"{c:.1f}", f"{100 * (b - c) / b:+.1f}"]
    lines.append(" | ".join(parts))

text = "\n".join(lines)
print(text)
with open("results/compression_improvement.txt", "w") as f:
    f.write(text + "\n")
print("\nPositive = faster than baseline. Saved results/compression_improvement.txt")