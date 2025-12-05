import os
from pathlib import Path

import numpy as np
import xarray as xr
from sqlalchemy import text

from .db import engine  # your existing db.py

CORE_ROOT = Path(r"D:\SIH\Current project Main Restart\chatgpt sih data\data_argo_final\data_netcdf\data_core_5yr")  # same as download script


def juld_to_timestamp(juld):
    import datetime as dt
    import pandas as pd

    if juld is None:
        return None

    val = np.atleast_1d(juld)[0]
    if isinstance(val, (np.datetime64, dt.datetime)):
        return pd.to_datetime(val).to_pydatetime()

    try:
        days = float(val)
    except Exception:
        return None

    if days < -100000 or days > 100000:
        return None

    origin = dt.datetime(1950, 1, 1)
    return origin + dt.timedelta(days=days)


def qc_char_to_int_array(qc_arr):
    if qc_arr is None:
        return None
    qc_str = qc_arr.astype("U")
    out = np.full(qc_str.shape, None, dtype=object)
    for val in np.unique(qc_str):
        if val in ("0", "1"):
            out[qc_str == val] = 1
        elif val in ("2", "3", "4", "5", "6", "7", "8"):
            out[qc_str == val] = int(val)
    return out


def pick_var_with_source(ds, base_name: str):
    adj_name = base_name + "_ADJUSTED"
    src = "RAW"
    var = ds[base_name]

    if adj_name in ds:
        arr = ds[adj_name].values
        if not np.all(np.isnan(arr)):
            var = ds[adj_name]
            src = "ADJUSTED"

    qc_name = base_name + "_ADJUSTED_QC" if src == "ADJUSTED" else base_name + "_QC"
    if qc_name in ds:
        qc_raw = ds[qc_name].values
        qc = qc_char_to_int_array(qc_raw)
    else:
        qc = None

    return var, src, qc


def ingest_core_file(nc_path: Path, dac: str):
    print(f"\n📄 Ingesting CORE: {nc_path}")
    ds = xr.open_dataset(nc_path)

    if "PLATFORM_NUMBER" in ds:
        float_id = str(ds["PLATFORM_NUMBER"].values[0]).strip()
    else:
        fname = nc_path.name
        float_id = fname.split("_")[0].lstrip("RD")

    n_prof = ds.dims.get("N_PROF", 1)
    print(f"   float_id={float_id}, N_PROF={n_prof}")

    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO floats (float_id, dac, ocean, platform_type)
            VALUES (:float_id, :dac, :ocean, :platform_type)
            ON CONFLICT (float_id) DO UPDATE
              SET dac = EXCLUDED.dac;
        """), {
            "float_id": float_id,
            "dac": dac,
            "ocean": "IO",
            "platform_type": "ARGO",
        })

    lat_var  = ds["LATITUDE"]
    lon_var  = ds["LONGITUDE"]
    juld_var = ds["JULD"] if "JULD" in ds else None
    cyc_var  = ds["CYCLE_NUMBER"] if "CYCLE_NUMBER" in ds else None
    data_mode_var = ds["DATA_MODE"] if "DATA_MODE" in ds else None

    pres_var, pres_src, pres_qc = pick_var_with_source(ds, "PRES")
    temp_var, temp_src, temp_qc = pick_var_with_source(ds, "TEMP")
    psal_var, psal_src, psal_qc = pick_var_with_source(ds, "PSAL")

    with engine.begin() as conn:
        for i in range(n_prof):
            lat = float(lat_var.values[i])
            lon = float(lon_var.values[i])
            profile_time = juld_to_timestamp(juld_var.values[i]) if juld_var is not None else None
            cycle_number = int(cyc_var.values[i]) if cyc_var is not None else i

            data_mode = None
            if data_mode_var is not None:
                dm_val = data_mode_var.values
                dm_val = dm_val[i] if hasattr(dm_val, "__len__") else dm_val
                if isinstance(dm_val, bytes):
                    dm_val = dm_val.decode("utf-8")
                data_mode = str(dm_val).strip()

            result = conn.execute(text("""
                INSERT INTO profiles (
                    float_id, cycle_number, profile_time,
                    latitude, longitude, position_geom,
                    data_mode, has_bgc
                )
                VALUES (
                    :float_id, :cycle_number, :profile_time,
                    :lat, :lon, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
                    :data_mode, FALSE
                )
                ON CONFLICT (float_id, cycle_number, profile_time) DO NOTHING
                RETURNING profile_id;
            """), {
                "float_id": float_id,
                "cycle_number": cycle_number,
                "profile_time": profile_time,
                "lat": lat,
                "lon": lon,
                "data_mode": data_mode,
            })

            row = result.fetchone()
            if row is None:
                print(f"   → SKIP existing core profile float={float_id}, cycle={cycle_number}")
                continue

            profile_id = row[0]
            print(f"   → NEW core profile_id={profile_id}, cycle={cycle_number}")

            pres = pres_var.isel(N_PROF=i).values
            temp = temp_var.isel(N_PROF=i).values
            psal = psal_var.isel(N_PROF=i).values

            pres_q_arr = pres_qc[i, :] if pres_qc is not None else [None] * len(pres)
            temp_q_arr = temp_qc[i, :] if temp_qc is not None else [None] * len(temp)
            psal_q_arr = psal_qc[i, :] if psal_qc is not None else [None] * len(psal)

            rows = []
            for idx in range(len(pres)):
                p = pres[idx]
                t = temp[idx]
                s = psal[idx]
                pq = pres_q_arr[idx]
                tq = temp_q_arr[idx]
                sq = psal_q_arr[idx]

                if np.isnan(p) and np.isnan(t) and np.isnan(s):
                    continue

                rows.append({
                    "profile_id": profile_id,
                    "pressure_dbar": float(p) if not np.isnan(p) else None,
                    "pressure_source": pres_src,
                    "pressure_qc": int(pq) if pq is not None else None,
                    "depth_m": float(p) if not np.isnan(p) else None,
                    "temperature_c": float(t) if not np.isnan(t) else None,
                    "temperature_source": temp_src,
                    "temperature_qc": int(tq) if tq is not None else None,
                    "salinity_psu": float(s) if not np.isnan(s) else None,
                    "salinity_source": psal_src,
                    "salinity_qc": int(sq) if sq is not None else None,
                })

            if rows:
                conn.execute(text("""
                    INSERT INTO measurements (
                        profile_id,
                        pressure_dbar, pressure_source, pressure_qc,
                        depth_m,
                        temperature_c, temperature_source, temperature_qc,
                        salinity_psu, salinity_source, salinity_qc
                    )
                    VALUES (
                        :profile_id,
                        :pressure_dbar, :pressure_source, :pressure_qc,
                        :depth_m,
                        :temperature_c, :temperature_source, :temperature_qc,
                        :salinity_psu, :salinity_source, :salinity_qc
                    );
                """), rows)


def ingest_core_root(root: Path):
    from tqdm import tqdm
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        for fname in filenames:
            if not fname.endswith(".nc"):
                continue
            files.append(Path(dirpath) / fname)

    print(f"Found {len(files)} core files to ingest.")
    for path in tqdm(files, desc="CORE ingest"):
        dac = path.parts[-4]  # dac/190xxxx/profiles/file.nc
        try:
            ingest_core_file(path, dac=dac)
        except Exception as e:
            print(f"❌ Error core ingest {path}: {e}")


if __name__ == "__main__":
    ingest_core_root(CORE_ROOT)
