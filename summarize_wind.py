"""
Read every daily wind_logs CSV (wind_logs/YYYY/MM/wind_realtime_YYYY-MM-DD.csv)
up through yesterday (today's file is skipped since it's still incomplete),
and compute per-wind-farm daily statistics.

Output mirrors the same year/month folder structure as wind_logs:
    wind_summaries/YYYY/MM/wind_summary_YYYY-MM-DD.csv
One file per day, one row per farm inside it.

Per farm, per day:
- avg_MW: average instantaneous net generation for that farm that day
- capacity_MW: the farm's installed capacity (裝置容量) as reported that day
- capacity_factor_pct: avg_MW / capacity_MW * 100
- est_MWh: avg_MW * 24 -- an ESTIMATE of that day's energy output, derived
  from averaging power snapshots taken every ~30 min. This is not a metered
  reading; treat it as an approximation, not ground truth.
- num_samples: how many snapshots that day contributed to the average

A day is only (re)processed if its summary file doesn't already exist, so
re-running this script is safe and cheap -- it won't recompute or duplicate
days it has already summarized.

Meant to be run on a schedule (e.g. once a day) by a GitHub Actions
workflow, same pattern as fetch_wind.py.
"""

import csv
import glob
import os
from datetime import datetime

import pandas as pd

WIND_LOGS_DIR = "wind_logs"
SUMMARY_DIR = "wind_summaries"

# Rows with this 機組名稱 are a system-wide subtotal, not an individual farm --
# exclude from per-farm averaging.
SUBTOTAL_LABEL = "小計(註5)"

SUMMARY_FIELDNAMES = [
    "date",
    "機組名稱",
    "avg_MW",
    "capacity_MW",
    "capacity_factor_pct",
    "est_MWh",
    "num_samples",
]


def find_daily_log_files():
    """
    Find every daily log file, mapped by the date encoded in its filename
    (wind_realtime_YYYY-MM-DD.csv), excluding today (incomplete) and any
    date whose summary file already exists.
    """
    today = datetime.now().date()

    pattern = os.path.join(WIND_LOGS_DIR, "*", "*", "wind_realtime_*.csv")
    candidates = {}

    for path in glob.glob(pattern):
        filename = os.path.basename(path)
        date_str = filename.removeprefix("wind_realtime_").removesuffix(".csv")

        try:
            file_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            continue  # skip anything that doesn't match the expected pattern

        if file_date >= today:
            continue  # skip today (and any future-dated file) -- incomplete

        out_path = summary_path_for_date(file_date, date_str)
        if os.path.isfile(out_path):
            continue  # already summarized, skip

        candidates[date_str] = (path, file_date)

    return dict(sorted(candidates.items()))


def summary_path_for_date(file_date, date_str):
    year_folder = file_date.strftime("%Y")
    month_folder = file_date.strftime("%m")
    out_dir = os.path.join(SUMMARY_DIR, year_folder, month_folder)
    return os.path.join(out_dir, f"wind_summary_{date_str}.csv")


def summarize_day(date_str, path):
    """Compute per-farm stats for a single day's log file. Returns a list of dict rows."""
    df = pd.read_csv(path, encoding="utf-8-sig")

    # Exclude the system-wide subtotal row -- we only want individual farms.
    df = df[df["機組名稱"] != SUBTOTAL_LABEL].copy()

    # Some readings show "-" for unavailable data; coerce to NaN and drop.
    df["淨發電量(MW)"] = pd.to_numeric(df["淨發電量(MW)"], errors="coerce")
    df["裝置容量(MW)"] = pd.to_numeric(df["裝置容量(MW)"], errors="coerce")

    rows = []
    for farm_name, group in df.groupby("機組名稱"):
        valid = group.dropna(subset=["淨發電量(MW)"])
        if valid.empty:
            continue

        avg_mw = valid["淨發電量(MW)"].mean()
        # Capacity can occasionally vary/be missing across readings in a day
        # (e.g. maintenance changes); take the most common non-null value.
        capacity_series = valid["裝置容量(MW)"].dropna()
        capacity_mw = capacity_series.mode().iloc[0] if not capacity_series.empty else None

        capacity_factor = (avg_mw / capacity_mw * 100) if capacity_mw else None
        est_mwh = avg_mw * 24

        rows.append(
            {
                "date": date_str,
                "機組名稱": farm_name,
                "avg_MW": round(avg_mw, 3),
                "capacity_MW": capacity_mw,
                "capacity_factor_pct": round(capacity_factor, 2) if capacity_factor is not None else "",
                "est_MWh": round(est_mwh, 2),
                "num_samples": len(valid),
            }
        )

    return rows


def write_summary_file(date_str, file_date, rows):
    out_path = summary_path_for_date(file_date, date_str)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main():
    files_to_process = find_daily_log_files()

    if not files_to_process:
        print("No new completed days to summarize.")
        return

    total_days = 0
    total_rows = 0
    for date_str, (path, file_date) in files_to_process.items():
        day_rows = summarize_day(date_str, path)
        write_summary_file(date_str, file_date, day_rows)
        print(f"Summarized {date_str}: {len(day_rows)} farms -> {summary_path_for_date(file_date, date_str)}")
        total_days += 1
        total_rows += len(day_rows)

    print(f"Done. Wrote {total_days} new daily summary file(s), {total_rows} farm-day rows total.")


if __name__ == "__main__":
    main()
