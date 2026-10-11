"""Section 8: next-day hourly regional consumption forecast (offline).
8.1 dataset, chronological split, features, lag checks
8.2 previous-day baseline
8.3 Ridge regression, >= 2 configurations, validation selection, frozen test predictions
8.4 metrics overall and per region, peak-hour errors, forecast plot"""
import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from db_config import get_connection

warnings.filterwarnings("ignore", message="pandas only supports SQLAlchemy")
pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 20)

TZ = "Africa/Kigali"
T = lambda s: pd.Timestamp(s, tz=TZ)
SPLITS = {"train": (T("2026-09-01"), T("2026-09-15")),
          "validation": (T("2026-09-15"), T("2026-09-22")),
          "test": (T("2026-09-22"), T("2026-09-29"))}
NUMERIC = ["lag_24", "lag_168", "prev_day_total", "same_hour_mean_7d"]
CATEG = ["region", "hour", "dow"]
CONFIGS = [("C1", 0.1), ("C2", 1.0), ("C3", 10.0), ("C4", 100.0)]
PLOT_REGION = "Region 8"
OUT = "results"


def mae(err):
    return float(np.mean(np.abs(err)))


def rmse(err):
    return float(np.sqrt(np.mean(np.square(err))))


def header(title):
    print("\n" + "=" * 100 + f"\n{title}\n" + "=" * 100)


def main():
    # ------------------------------------------------------------------ 8.1
    header("8.1  DATASET: one row per region and CAT hour (sum of energy_kwh, cleaned readings)")
    conn = get_connection()
    raw = pd.read_sql_query("""
        SELECT time_bucket('1 hour', e.event_time, 'Africa/Kigali') AS hour_cat, m.region,
               sum(e.energy_kwh) AS energy_kwh, count(*) AS readings
        FROM energy_readings e JOIN meters m ON m.meter_id = e.meter_id
        GROUP BY 1, 2""", conn)
    conn.close()
    raw["hour_cat"] = pd.to_datetime(raw["hour_cat"], utc=True).dt.tz_convert(TZ)

    hours = pd.date_range(T("2026-09-01 00:00"), periods=28 * 24, freq="h")
    regions = sorted(raw["region"].unique(), key=lambda r: int(r.split()[1]))
    grid = pd.MultiIndex.from_product([regions, hours], names=["region", "hour_cat"]).to_frame(index=False)
    df = grid.merge(raw, on=["region", "hour_cat"], how="left")
    absent = int(df["energy_kwh"].isna().sum())
    df["readings"] = df["readings"].fillna(0).astype(int)
    df = df.sort_values(["region", "hour_cat"]).reset_index(drop=True)
    print(f"Rows: {len(df):,} (10 regions x 672 hours) | absent region-hours: {absent} "
          "(absent hours would be kept as missing, never filled with zero)")
    print(f"Readings per region-hour: min {df['readings'].min()}, max {df['readings'].max()}, "
          f"mean {df['readings'].mean():.1f} (planned 1,600 = 400 meters x 4 intervals); "
          f"total {df['readings'].sum():,}")
    print(f"Total energy in dataset: {df['energy_kwh'].sum():,.3f} kWh")

    # Features (all computed from values strictly before the forecast origin)
    df["origin"] = df["hour_cat"].dt.normalize()            # 00:00 CAT of the target day
    df["hour"] = df["hour_cat"].dt.hour
    df["dow"] = df["hour_cat"].dt.dayofweek
    g = df.groupby("region")["energy_kwh"]
    df["lag_24"] = g.shift(24)
    df["lag_168"] = g.shift(168)
    df["same_hour_mean_7d"] = sum(g.shift(24 * k) for k in range(1, 8)) / 7
    daily = df.groupby(["region", "origin"])["energy_kwh"].sum(min_count=24).rename("day_total").reset_index()
    daily["origin"] = daily["origin"] + pd.Timedelta(days=1)  # previous day's total, known at next origin
    df = df.merge(daily.rename(columns={"day_total": "prev_day_total"}), on=["region", "origin"], how="left")

    # Source timestamps: latest data hour used by each feature, must precede the origin
    df["src_lag_24"] = df["hour_cat"] - pd.Timedelta(hours=24)
    df["src_lag_168"] = df["hour_cat"] - pd.Timedelta(hours=168)
    df["src_prev_day_total_last"] = df["origin"] - pd.Timedelta(hours=1)
    df["src_same_hour_mean_7d_last"] = df["hour_cat"] - pd.Timedelta(hours=24)

    print("\nFeatures:")
    feat_rows = []
    first = df.dropna(subset=["lag_24"])["hour_cat"].min()
    feat_info = [("hour", "calendar: hour of day (CAT)", "0 h (target time)", "lag_none"),
                 ("dow", "calendar: day of week", "0 h (target time)", "lag_none"),
                 ("region", "categorical: region", "n/a", "lag_none"),
                 ("lag_24", "same hour, previous day", "24 h", "lag_24"),
                 ("lag_168", "same hour, one week earlier", "168 h", "lag_168"),
                 ("prev_day_total", "region total over the 24 h before the origin", "24 h window", "prev_day_total"),
                 ("same_hour_mean_7d", "mean of the same hour over the previous 7 days", "24-168 h (7 values)", "same_hour_mean_7d")]
    for name, desc, window, col in feat_info:
        earliest = df["hour_cat"].min() if col == "lag_none" else df.dropna(subset=[col])["hour_cat"].min()
        feat_rows.append({"feature": name, "description": desc, "lag/window": window,
                          "earliest usable target": earliest.strftime("%Y-%m-%d %H:%M CAT")})
    print(pd.DataFrame(feat_rows).to_string(index=False))

    checks = {c: bool((df[c] < df["origin"]).all())
              for c in ["src_lag_24", "src_lag_168", "src_prev_day_total_last", "src_same_hour_mean_7d_last"]}
    print("\nLag check - every source timestamp precedes its forecast origin:")
    for c, ok in checks.items():
        print(f"  {c:<28} {ok}")
    print(f"  ALL LAG SOURCES BEFORE ORIGIN: {all(checks.values())}")

    print("\nFeature examples (Region 1, first test day):")
    ex = df[(df["region"] == "Region 1") & (df["hour_cat"] >= T("2026-09-22 12:00"))].head(3)
    print(ex[["hour_cat", "origin", "energy_kwh", "lag_24", "src_lag_24", "lag_168",
              "src_lag_168", "prev_day_total", "same_hour_mean_7d"]].to_string(index=False))

    # Splits by target timestamp
    def split(name):
        a, b = SPLITS[name]
        return df[(df["hour_cat"] >= a) & (df["hour_cat"] < b)].copy()
    train_all, val, test = split("train"), split("validation"), split("test")
    train = train_all.dropna(subset=NUMERIC + ["energy_kwh"])
    print("\nChronological split (by target timestamp, CAT):")
    for name, part in [("train", train_all), ("validation", val), ("test", test)]:
        print(f"  {name:<10} rows {len(part):>5}  {part['hour_cat'].min():%Y-%m-%d %H:%M} to "
              f"{part['hour_cat'].max():%Y-%m-%d %H:%M}")
    print(f"Training rows before lookback exclusion: {len(train_all)} | excluded (lacking the "
          f"168-hour lookback): {len(train_all) - len(train)} | retained: {len(train)} "
          f"({train['hour_cat'].min():%Y-%m-%d %H:%M} onward). Same rows used for every configuration.")
    df.to_csv(f"{OUT}/forecast_dataset.csv", index=False)

    # ------------------------------------------------------------------ 8.2
    header("8.2  PREVIOUS-DAY BASELINE on the test week (prediction = same hour of the previous day)")
    test = test.copy()
    test["baseline"] = test["lag_24"]
    b_err = test["baseline"] - test["energy_kwh"]
    print(f"Test predictions: {test['baseline'].notna().sum()} (7 days x 24 hours x 10 regions)")
    print(f"Baseline MAE  = {mae(b_err):.3f} kWh")
    print(f"Baseline RMSE = {rmse(b_err):.3f} kWh")
    print(test[["region", "hour_cat", "energy_kwh", "baseline"]].head(5).to_string(index=False))

    # ------------------------------------------------------------------ 8.3
    header("8.3  RIDGE REGRESSION: configurations, validation, frozen model, test predictions")
    print(f"Shared predictors: categorical {CATEG} (one-hot) + numeric {NUMERIC} (standardised); "
          "preprocessing fitted on training data only.")
    results, models = [], {}
    for cid, alpha in CONFIGS:
        pipe = Pipeline([
            ("prep", ColumnTransformer([
                ("cat", OneHotEncoder(handle_unknown="ignore"), CATEG),
                ("num", StandardScaler(), NUMERIC)])),
            ("model", Ridge(alpha=alpha))])
        pipe.fit(train[CATEG + NUMERIC], train["energy_kwh"])
        v_err = pipe.predict(val[CATEG + NUMERIC]) - val["energy_kwh"].to_numpy()
        results.append({"config": cid, "settings": f"Ridge(alpha={alpha})",
                        "train_rows": len(train), "validation_rows": len(val),
                        "validation_MAE_kWh": round(mae(v_err), 3),
                        "validation_RMSE_kWh": round(rmse(v_err), 3)})
        models[cid] = pipe
    vt = pd.DataFrame(results)
    print(vt.to_string(index=False))
    vt.to_csv(f"{OUT}/forecast_validation.csv", index=False)
    best = vt.loc[vt["validation_MAE_kWh"].idxmin()]
    frozen = models[best["config"]]
    print(f"\nSelected (lowest validation MAE): {best['config']} {best['settings']} - model and "
          "preprocessing FROZEN; no refitting on validation or test data.")

    test["model"] = frozen.predict(test[CATEG + NUMERIC])
    m_err = test["model"] - test["energy_kwh"]
    print(f"Test predictions: {test['model'].notna().sum()}")
    print(test[["region", "hour_cat", "energy_kwh", "baseline", "model"]].head(5).to_string(index=False))

    # ------------------------------------------------------------------ 8.4
    header("8.4  FORECAST USEFULNESS (error = predicted - actual; MAE and RMSE in kWh)")
    print(f"ALL {len(test)} test observations: baseline MAE {mae(b_err):.3f}, RMSE {rmse(b_err):.3f} | "
          f"model MAE {mae(m_err):.3f}, RMSE {rmse(m_err):.3f} | MAE improvement "
          f"{100 * (mae(b_err) - mae(m_err)) / mae(b_err):.1f} %")
    per = []
    for region in regions:
        t = test[test["region"] == region]
        be, me = t["baseline"] - t["energy_kwh"], t["model"] - t["energy_kwh"]
        per.append({"region": region, "baseline_MAE": round(mae(be), 3), "baseline_RMSE": round(rmse(be), 3),
                    "model_MAE": round(mae(me), 3), "model_RMSE": round(rmse(me), 3),
                    "model_better_MAE": mae(me) < mae(be)})
    per = pd.DataFrame(per)
    print("\nPer region:")
    print(per.to_string(index=False))
    per.to_csv(f"{OUT}/forecast_metrics_by_region.csv", index=False)

    print("\nHighest actual test hour per region (ties broken by earliest time):")
    peaks = (test.sort_values(["region", "energy_kwh", "hour_cat"], ascending=[True, False, True])
                 .groupby("region", sort=False).head(1))
    peaks = peaks.set_index("region").loc[regions].reset_index()
    peaks["baseline_abs_err"] = (peaks["baseline"] - peaks["energy_kwh"]).abs()
    peaks["model_abs_err"] = (peaks["model"] - peaks["energy_kwh"]).abs()
    peaks["hour_cat"] = peaks["hour_cat"].dt.strftime("%a %Y-%m-%d %H:%M")
    print(peaks[["region", "hour_cat", "energy_kwh", "baseline", "baseline_abs_err",
                 "model", "model_abs_err"]].round(3).to_string(index=False))
    peaks.to_csv(f"{OUT}/forecast_peak_hours.csv", index=False)
    test.to_csv(f"{OUT}/forecast_test_predictions.csv", index=False)

    t = test[test["region"] == PLOT_REGION]
    fig, ax = plt.subplots(figsize=(14, 5))
    ax.plot(t["hour_cat"], t["energy_kwh"], label="Actual", color="black", linewidth=1.8)
    ax.plot(t["hour_cat"], t["baseline"], label="Previous-day baseline", color="tab:orange", linestyle="--")
    ax.plot(t["hour_cat"], t["model"], label=f"Ridge model ({best['config']})", color="tab:blue")
    ax.set_title(f"{PLOT_REGION}: actual vs forecast hourly consumption, test week 22-28 Sep 2026 (CAT)")
    ax.set_ylabel("Energy (kWh per hour)")
    ax.set_xlabel("CAT hour")
    ax.legend()
    plt.tight_layout()
    plt.savefig(f"{OUT}/charts/8_4_forecast_{PLOT_REGION.replace(' ', '_')}.png", dpi=120)
    plt.close(fig)
    print(f"\nPlot saved: {OUT}/charts/8_4_forecast_{PLOT_REGION.replace(' ', '_')}.png")


if __name__ == "__main__":
    main()