"""
Fetch Taipower's real-time unit-level generation JSON, filter to wind (風力)
units, and save it to a daily CSV file inside this repo's wind_logs/ folder.

Behavior:
- One CSV file per calendar date (based on the report's own DateTime field),
  e.g. wind_logs/wind_realtime_2026-08-20.csv
- If that day's file already exists, new rows are appended to the end.
- If it doesn't exist yet (new day), a fresh file is created with headers.
- Skips writing if this exact reported_time was already saved (avoids
  duplicate snapshots if the workflow runs faster than Taipower updates).

Meant to be run on a schedule by the GitHub Actions workflow in
.github/workflows/fetch_wind.yml — no local setup needed.
"""

import csv
import os
from datetime import datetime
import json
import requests

URL = "https://service.taipower.com.tw/data/opendata/apply/file/d006001/001.json"

OUTPUT_DIR = "wind_logs"

FIELDNAMES = [
    "fetch_time",
    "reported_time",
    "機組類型",
    "機組名稱",
    "裝置容量(MW)",
    "淨發電量(MW)",
    "淨發電量/裝置容量比(%)",
    "備註",
]


def fetch_and_save():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    resp = requests.get(URL, timeout=15)
    resp.raise_for_status()
    data = json.loads(resp.content.decode("utf-8-sig"))

    fetch_time = datetime.now().isoformat(timespec="seconds")
    reported_time = data.get("DateTime", "")

    try:
        report_date = datetime.fromisoformat(reported_time).date().isoformat()
    except (ValueError, TypeError):
        report_date = datetime.now().date().isoformat()

    wind_rows = [r for r in data.get("aaData", []) if r.get("機組類型") == "風力"]

    if not wind_rows:
        print("No wind rows found in this pull — skipping.")
        return

    report_dt = datetime.fromisoformat(reported_time) if reported_time else datetime.now()
    year_folder = report_dt.strftime("%Y")
    month_folder = report_dt.strftime("%m")

    out_dir = os.path.join(OUTPUT_DIR, year_folder, month_folder)
    os.makedirs(out_dir, exist_ok=True)

    out_path = os.path.join(out_dir, f"wind_realtime_{report_date}.csv")
    file_exists = os.path.isfile(out_path)

    if file_exists:
        with open(out_path, newline="", encoding="utf-8-sig") as f:
            already_have = any(
                row["reported_time"] == reported_time for row in csv.DictReader(f)
            )
        if already_have:
            print(f"reported_time {reported_time} already logged in {out_path} — skipping.")
            return

    with open(out_path, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if not file_exists:
            writer.writeheader()
        for r in wind_rows:
            writer.writerow(
                {
                    "fetch_time": fetch_time,
                    "reported_time": reported_time,
                    "機組類型": r.get("機組類型", ""),
                    "機組名稱": r.get("機組名稱", ""),
                    "裝置容量(MW)": r.get("裝置容量(MW)", ""),
                    "淨發電量(MW)": r.get("淨發電量(MW)", ""),
                    "淨發電量/裝置容量比(%)": r.get("淨發電量/裝置容量比(%)", ""),
                    "備註": r.get("備註", ""),
                }
            )

    print(f"Saved {len(wind_rows)} wind rows to {out_path}")


if __name__ == "__main__":
    fetch_and_save()
