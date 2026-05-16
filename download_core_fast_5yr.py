import os
from pathlib import Path
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd

# ---------- CONFIG ----------
BASE_URL = "https://data-argo.ifremer.fr"
INDEX_URL = f"{BASE_URL}/ar_index_global_prof.txt.gz"   # core profiles index
DAC_URL   = f"{BASE_URL}/dac"

OUT_DIR = Path(r"D:\SIH\Current project Main Restart\chatgpt sih data\data_argo_final\data_netcdf\data_core_5yr")
OUT_DIR.mkdir(parents=True, exist_ok=True)

LAT_MIN, LAT_MAX = -40, 30
LON_MIN, LON_MAX = 20, 120

MIN_DATE = datetime.utcnow() - timedelta(days=5 * 365)

MAX_WORKERS = 16

# ---------- SESSION ----------
def make_session():
    s = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[500, 502, 503, 504],
    )
    adapter = HTTPAdapter(pool_connections=MAX_WORKERS,
                          pool_maxsize=MAX_WORKERS,
                          max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s

session = make_session()

# ---------- INDEX ----------
def download_index() -> Path:
    local_path = OUT_DIR / "ar_index_global_prof.txt.gz"
    if local_path.exists() and local_path.stat().st_size > 0:
        print(f"✅ Core index already present: {local_path}")
        return local_path

    print(f"⬇️ Downloading core index from {INDEX_URL}...")
    with session.get(INDEX_URL, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(local_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=16384):
                f.write(chunk)
    print("✅ Core index downloaded.")
    return local_path


def get_core_file_list(idx_path: Path):
    print("🔍 Parsing core index & filtering Indian Ocean (last 5 years)...")

    cols = [
        "file", "date", "latitude", "longitude",
        "ocean", "profiler_type", "institution", "date_update"
    ]

    df = pd.read_csv(
        idx_path,
        compression="gzip",
        header=8,
        names=cols,
        dtype=str,
        skipinitialspace=True,
    )

    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    df["date_dt"] = pd.to_datetime(df["date"], format="%Y%m%d%H%M%S", errors="coerce")

    df = df.dropna(subset=["latitude", "longitude", "date_dt"])

    mask = (
        df["latitude"].between(LAT_MIN, LAT_MAX)
        & df["longitude"].between(LON_MIN, LON_MAX)
        & (df["date_dt"] >= MIN_DATE)
    )

    df = df[mask]

    print(f"📊 Core profiles selected: {len(df)}")
    return df["file"].tolist()

# ---------- DOWNLOAD ----------
def download_one(rel_path: str):
    rel_path = rel_path.strip()
    url = f"{DAC_URL}/{rel_path}"
    local_path = OUT_DIR / rel_path

    if local_path.exists() and local_path.stat().st_size > 1024:
        return 0  # skipped

    local_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with session.get(url, stream=True, timeout=30) as r:
            r.raise_for_status()
            with open(local_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        return 1
    except Exception as e:
        return f"{rel_path}|{e}"


def main():
    idx_path = download_index()
    files = get_core_file_list(idx_path)

    if not files:
        print("⚠️ No core files matched filters.")
        return

    print(f"🚀 Downloading {len(files)} core files with {MAX_WORKERS} workers...")

    from tqdm import tqdm
    new = 0
    errors = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(download_one, f): f for f in files}
        for fut in tqdm(as_completed(futures), total=len(futures), unit="file"):
            res = fut.result()
            if res == 1:
                new += 1
            elif res == 0:
                continue
            else:
                errors.append(res)

    print("\n========== CORE DOWNLOAD SUMMARY ==========")
    print(f"New files: {new}")
    print(f"Errors: {len(errors)}")
    if errors:
        print("First few errors:", errors[:5])


if __name__ == "__main__":
    main()
