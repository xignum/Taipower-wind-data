"""
Read every daily wind_logs CSV (wind_logs/YYYY/MM/wind_realtime_YYYY-MM-DD.csv)
up through yesterday (today's file is skipped since it's still incomplete),
and compute per-wind-farm daily statistics:

- avg_MW: average instantaneous net generation for that farm that day
- capacity_MW: the farm's installed capacity (裝置容量) as reported that day
- capacity_factor_pct: avg_MW / capacity_MW * 100
- est_MWh: avg_MW * 24 -- an ESTIMATE of that day's energy output, derived
  from averaging power snapshots taken every ~30 min. This is not a metered
  reading; treat it as an approximation, not ground truth.
- num_samples: how many snapshots that day contributed to the average
  (useful for spotting days with missing/incomplete data)

Results are appended to a single running file:
    wind_summaries/daily_farm_averages.csv

Only dates not already present in that summary file are processed and
added, so re-running this script is safe and cheap -- it won't recompute
or duplicate days it has already summarized.

Meant to be run on a schedule (e.g. once a day) by a GitHub Actions
workflow, same pattern as fetch_wind.py.
"""

import csv
import glob
import os
from datetime import datetime, timedelta

import pandas as pd

WIND_LOGS_DIR = "wind_logs"
SUMMARY_DIR = "wind_summaries"
SUMMARY_PATH = os.path.join(SUMMARY_DIR, "daily_farm_averages.csv")

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


def get_already_summarized_dates():
    """Return the set of date strings already present in the summary file."""
    if not os.path.isfile(SUMMARY_PATH):
        return set()
    with open(SUMMARY_PATH, newline="", encoding="utf-8-sig") as f:
        return {row["date"] for row in csv.DictReader(f)}


def find_daily_log_files():
    """
    Find every daily log file, mapped by the date encoded in its filename
    (wind_realtime_YYYY-MM-DD.csv), excluding today (incomplete) and any
    date already summarized.
    """
    today = datetime.now().date()
    already_done = get_already_summarized_dates()

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
        if date_str in already_done:
            continue  # already summarized, skip

        candidates[date_str] = path

    return dict(sorted(candidates.items()))


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


def main():
    os.makedirs(SUMMARY_DIR, exist_ok=True)

    files_to_process = find_daily_log_files()

    if not files_to_process:
        print("No new completed days to summarize.")
        return

    file_exists = os.path.isfile(SUMMARY_PATH)

    with open(SUMMARY_PATH, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDNAMES)
        if not file_exists:
            writer.writeheader()

        total_rows_written = 0
        for date_str, path in files_to_process.items():
            day_rows = summarize_day(date_str, path)
            for row in day_rows:
                writer.writerow(row)
            total_rows_written += len(day_rows)
            print(f"Summarized {date_str}: {len(day_rows)} farms")

    print(f"Done. Added {total_rows_written} farm-day rows across {len(files_to_process)} new day(s).")


if __name__ == "__main__":
    main()
