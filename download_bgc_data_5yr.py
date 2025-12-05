# backend/download_bgc_profiles.py

import os
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

# ---- CONFIG ----
ARGO_BGC_INDEX_URL = "https://data-argo.ifremer.fr/argo_bio-profile_index.txt.gz"
OUT_DIR = Path(r"D:\SIH\chatgpt_sih_data\data_bgc")  # 👈 change to your desired BGC root
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Indian Ocean bounds (as per problem statement)
LAT_MIN, LAT_MAX = -40, 30
LON_MIN, LON_MAX = 20, 120

# Last 5 years
MIN_DATE = datetime.utcnow() - timedelta(days=5 * 365)


def download_index_file() -> Path:
    """
    Download argo_bio-profile_index.txt.gz into OUT_DIR and return its path.
    """
    idx_path = OUT_DIR / "argo_bio-profile_index.txt.gz"
    if idx_path.exists():
        print(f"Index already exists at {idx_path}")
        return idx_path

    print(f"Downloading BGC index from {ARGO_BGC_INDEX_URL}")
    resp = requests.get(ARGO_BGC_INDEX_URL, stream=True, timeout=60)
    resp.raise_for_status()
    with open(idx_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)

    print(f"Saved index to {idx_path}")
    return idx_path


def load_bgc_index(idx_path: Path) -> pd.DataFrame:
    """
    Load argo_bio-profile_index.txt.gz into a DataFrame with columns:
    file, date, latitude, longitude, ocean, profiler_type, institution,
    parameters, parameter_data_mode, date_update

    Then filter to Indian Ocean + last 5 years.
    """
    print(f"Reading index: {idx_path}")

    # According to the Argo manual, header row is the first non-# line
    cols = [
        "file", "date", "latitude", "longitude",
        "ocean", "profiler_type", "institution",
        "parameters", "parameter_data_mode", "date_update",
    ]

    df = pd.read_csv(
        idx_path,
        compression="gzip",
        comment="#",          # skip header comments that start with '#'
        header=0,             # first non-comment line is header
        names=cols,
        dtype=str,
        skipinitialspace=True # handle "file, date, latitude,..."
    )

    # Clean whitespace
    df = df.apply(lambda col: col.str.strip() if col.dtype == "object" else col)

    # Convert types
    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")

    # date is YYYYMMDDHHMISS (UTC)
    df["date_dt"] = pd.to_datetime(df["date"], format="%Y%m%d%H%M%S", errors="coerce")

    # Filter out invalid rows
    df = df.dropna(subset=["latitude", "longitude", "date_dt"])

    # Filter by region + last 5 years + ocean=I (Indian)
    mask = (
        (df["latitude"].between(LAT_MIN, LAT_MAX)) &
        (df["longitude"].between(LON_MIN, LON_MAX)) &
        (df["date_dt"] >= MIN_DATE) &
        (df["ocean"] == "I")
    )
    df = df[mask].copy()

    print(f"Rows after region+time filter: {len(df)}")

    # Drop duplicates just in case
    df = df.drop_duplicates(subset=["file"])

    return df


def download_bgc_files(df: pd.DataFrame, base_url: str = "https://data-argo.ifremer.fr/dac"):
    """
    Download each NetCDF file listed in df['file'] into OUT_DIR, preserving
    the DAC/float/profiles structure.
    """
    for i, rel_path in enumerate(df["file"], start=1):
        rel_path = rel_path.strip().lstrip('/')
        url = f"{base_url}/{rel_path}"
        local_path = OUT_DIR / rel_path.replace("/", os.sep)

        if local_path.exists():
            print(f"[{i}/{len(df)}] Already exists, skipping: {local_path}")
            continue

        local_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"[{i}/{len(df)}] Downloading {url} → {local_path}")

        try:
            resp = requests.get(url, stream=True, timeout=60)
            resp.raise_for_status()
            with open(local_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
        except Exception as e:
            print(f"  ❌ Error downloading {url}: {e}")


def main():
    idx_path = download_index_file()
    df = load_bgc_index(idx_path)
    print(f"Will download {len(df)} BGC profile files...")
    download_bgc_files(df)


if __name__ == "__main__":
    main()
