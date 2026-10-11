# Assignment I: Smart Energy Grid Analytics

Advanced Big Data Analytics, Adventist University of Central Africa (AUCA).
Group: Patrick Niyonshuti (101420), Erneste Uwimpuhwe (101414), Gisele Uwibereyeho (101366).

This project ingests readings from 4,000 smart meters (1 to 28 September 2026, CAT) into
PostgreSQL with TimescaleDB, compares chunk intervals and compression, analyses the data,
builds continuous aggregates and two dashboards, and forecasts next-day hourly demand.
The full explanation, measurements and screenshots are in the PDF report.

## Requirements

| Component | Version used |
|---|---|
| Windows 11, Command Prompt (not PowerShell) | |
| PostgreSQL | 18.6 |
| TimescaleDB | 2.30.2 |
| EMQX (MQTT broker, in Docker, container name `emqx`) | 6.3.1 |
| Python | 3.13 |
| Python packages | see `requirements.txt` (paho-mqtt 2.x is required) |

About 10 GB of free disk space is needed. All times are CAT (Africa/Kigali, UTC+02:00).

## Folder layout

```
src/        Python programs (smart_meter_simulator.py is the supplied generator, UNCHANGED)
sql/        SQL scripts (numbered in the order they are run)
results/    logs, CSV and JSON measurements, results/charts/ for charts
data/       generated CSV (created locally, NOT stored in the repository)
```

Create the folders that do not exist yet:

```
mkdir data results results\charts
```

## Passwords and secrets

No password is stored in the code. `src/db_config.py` reads the connection settings from
environment variables. In **every new Command Prompt window** set:

```
cd /d D:\auca_a1
venv\Scripts\activate
set PATH=C:\Program Files\PostgreSQL\18\bin;%PATH%
set PGPASSWORD=your_password
```

Replace `your_password` with the PostgreSQL password of the `postgres` user.
Optional variables: `PGHOST` (default localhost), `PGPORT` (5432), `PGDATABASE` (smart_grid), `PGUSER` (postgres).

## 1. One-time setup

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Create the tablespace, the database, the time zone and the TimescaleDB extension (run once, as the
`postgres` user). First create the folder `D:\pgdata` (the PostgreSQL service account must be able to write
to it), then run:

```
mkdir D:\pgdata
psql -U postgres -f sql\01_setup.sql
psql -U postgres -d smart_grid -f sql\01_check.sql
```

`sql\01_setup.sql` contains:

```
CREATE TABLESPACE d_space LOCATION 'D:/pgdata';
CREATE DATABASE smart_grid TABLESPACE d_space;
ALTER DATABASE smart_grid SET timezone = 'Africa/Kigali';
\c smart_grid
CREATE EXTENSION IF NOT EXISTS timescaledb;
```

The tablespace keeps the data on drive D: because drive C: had little free space. On a machine without that
constraint, the first line can be removed together with `TABLESPACE d_space` in the second line.
`sql\01_check.sql` shows the database, the enabled extension and the session time zone.

Start the MQTT broker (Docker Desktop must be running):

```
docker start emqx
docker exec emqx emqx ctl status
```

If the container does not exist yet, create it once from the EMQX image of the version listed above,
publishing port 1883 (MQTT) and naming it `emqx` (see Section 1.1 of the report).

## 2. Pilot check (assignment 1.3 and 9.2): run this first

The subscriber truncates `energy_live` itself, so it always starts empty.
Use two Command Prompt windows with the setup block above.

Window A (start first, wait for `READY`):

```
python src\pilot_subscriber.py
```

Window B (after READY):

```
python src\pilot_publisher.py
```

Expected: the publisher prints 2000 dictionaries taken (1994 unique, 6 duplicates) and
2000 messages acknowledged; the subscriber prints 2000 received and 2000 rows in
`energy_live` (it stops about 15 seconds after the last message). Verify the stored count:

```
psql -U postgres -d smart_grid -c "SELECT count(*) AS rows, count(DISTINCT (meter_id, event_time)) AS unique_pairs FROM energy_live;"
```

Expected: 2000 rows and 1994 unique pairs. If the broker is overloaded the subscriber can be
disconnected and fewer messages arrive; close other programs, run `docker restart emqx` and repeat.

## 3. Execution order

Run every step from `D:\auca_a1` with the setup block above. Steps depend on the earlier ones.

| Step | Command | Report section |
|---|---|---|
| 1 | `psql -U postgres -d smart_grid -f sql\02_tables.sql` | 1.2 |
| 2 | `python src\load_meters.py` | 1.2 |
| 3 | Pilot check (section 2 above) | 1.3 |
| 4 | `python src\capture_and_load.py`, then `psql -U postgres -d smart_grid -f sql\03_load_check.sql` (database checks after the load) | 2.1 |
| 5 | `psql -U postgres -d smart_grid -f sql\04_quality.sql` | 2.2 |
| 6 | `psql -U postgres -d smart_grid -f sql\05_clean.sql` | 2.3 |
| 7 | `psql -U postgres -d smart_grid -f sql\06_chunk_configs.sql`, then `psql -U postgres -d smart_grid -f sql\07_check_configs.sql` (checks of the three configurations) | 3.1 |
| 8 | `python src\benchmark.py --label section3 --tables energy_readings energy_readings_3h energy_readings_week` | 3.2 |
| 9 | `psql -U postgres -d smart_grid -f sql\08_plan_q1.sql` and `psql -U postgres -d smart_grid -f sql\08_plan_q3_q4.sql` (execution plans) | 3.3 |
| 10 | `psql -U postgres -d smart_grid -f sql\09_compression_setup.sql` | 4.1 |
| 11 | `python src\compress_load.py`, then `psql -U postgres -d smart_grid -f sql\10_compression_verify.sql` (compressed chunks and data checks) and `psql -U postgres -d smart_grid -f sql\11_compression_storage.sql` (storage statistics) | 4.1, 4.2 |
| 12 | `python src\benchmark.py --label section4 --tables energy_readings energy_time_compressed energy_meter_compressed` | 4.3 |
| 13 | `python src\improvement.py` | 4.3 |
| 14 | `python src\analysis_5_1.py`, `python src\analysis_5_2.py`, `python src\analysis_5_3.py` | 5.1 to 5.3 |
| 15 | `python src\anomaly_5_4.py` | 5.4 |
| 16 | `psql -U postgres -d smart_grid -f sql\12_caggs.sql` then `psql -U postgres -d smart_grid -f sql\13_caggs_check.sql` | 6.1 |
| 17 | `python src\freshness_6_2.py` | 6.2 |
| 18 | `python src\dashboard_app.py`, then open http://127.0.0.1:8050/raw and http://127.0.0.1:8050/aggregate | 7.1, 7.2 |
| 19 | `python src\dashboard_verify.py` | 7.3 |
| 20 | In the browser press **Run benchmark (1 + 10)** on each dashboard (background jobs paused), then `python src\dashboard_timing_summary.py` | 7.4 |
| 21 | `python src\forecast_8.py` | 8.1 to 8.4 |

Notes:

* `sql\09_compression_setup.sql` creates the two compressed tables and pauses their policies; resume the jobs after the measurements in 4.3.
* `sql\12_caggs.sql` creates the three continuous aggregates empty, refreshes September manually and then adds the refresh policies.
* For the benchmarks in Sections 3, 4 and 7, pause the background jobs and close other programs. To pause or resume jobs: `psql -U postgres -d smart_grid -c "SELECT job_id, (alter_job(job_id, scheduled => false)).scheduled FROM timescaledb_information.jobs WHERE proc_name IN ('policy_refresh_continuous_aggregate','policy_compression') ORDER BY job_id;"` (use `true` to resume).

## 4. Regenerating and loading the full dataset

The full generated dataset (10,696,848 readings as a CSV file) is kept **local** and is not in
the repository (`data/` is ignored by Git). To recreate it:

```
python src\capture_and_load.py
```

This consumes `iter_readings()` of the unchanged generator in batches of 100,000, writes
`data\energy_readings_full.csv`, bulk-loads it into the empty `energy_readings` table with `COPY`,
and checks that the generator, the CSV and the database all contain exactly 10,696,848 rows
(`dataset_info()` expected count). The path of the CSV is the constant `CSV_PATH` in
`src\capture_and_load.py`; change it if the project is not in `D:\auca_a1`.
The CSV may be deleted afterwards; it can be regenerated at any time.
Use `python src\capture_and_load.py --load-only` to reload an existing CSV into an empty table.

## 5. The supplied generator

`src\smart_meter_simulator.py` is the issued file, unchanged. Its SHA-256 hash is
`6b16d6bb3191e528844d0ec75656096d8bfb2e92c99f83e2b75d586bf21cfff8`; check it with:

```
certutil -hashfile src\smart_meter_simulator.py SHA256
```

## 6. Recorded results

Benchmark timings and measurements are saved in `results/` (for example `bench_section3_*.csv`,
`bench_section4_*.csv`, `compression_timings.csv`, `load_timings.json`, `dashboard_timings.csv`,
`dashboard_timing_summary.csv`, `forecast_validation.csv`, `forecast_metrics_by_region.csv`) and
charts in `results/charts/`. Environment details (hardware, software versions, PostgreSQL settings)
are recorded in Section 1.1 of the report.
