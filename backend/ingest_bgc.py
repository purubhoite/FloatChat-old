# backend/ingest_bgc.py

from pathlib import Path
from typing import Optional, Dict, Any, List

import os
import numpy as np
import xarray as xr
from sqlalchemy import text

from .db import engine
from .ingest_core import juld_to_timestamp, pick_var_with_source

# 👇 Change to your actual BGC root directory
BGC_ROOT = Path(
    r"D:\SIH\Current project Main Restart\chatgpt sih data\data_argo_final\data_netcdf\data_bgc_5yr"
)

# How close (in dbar) a BGC level must be to a core level
# to be considered "the same depth" when merging
PRESSURE_MATCH_TOL = 1.0  # you can tighten to 0.5 if grids are very similar


# ----------------------------------------------------
# Helpers
# ----------------------------------------------------
def _decode_data_mode(data_mode_var, i: int) -> Optional[str]:
    """
    Extract per-profile DATA_MODE as a clean string, or None.
    Handles scalar or 1D arrays, and bytes.
    """
    if data_mode_var is None:
        return None

    dm_val = data_mode_var.values
    dm_val = dm_val[i] if hasattr(dm_val, "__len__") else dm_val

    if isinstance(dm_val, bytes):
        dm_val = dm_val.decode("utf-8", errors="ignore")

    dm_str = str(dm_val).strip()
    return dm_str or None


def _extract_bgc_arrays_for_profile(
    ds,
    i: int,
    pres_var,
    doxy_var,
    chla_var,
    nitrate_var,
    ph_var,
    pres_qc,
    doxy_qc,
    chla_qc,
    nitrate_qc,
    ph_qc,
) -> Dict[str, Any]:
    """
    For profile index i, slice 1D arrays and QC flags for
    PRES + BGC variables and return them as numpy arrays.
    """
    pres = pres_var.isel(N_PROF=i).values

    pres_q_arr = pres_qc[i, :] if pres_qc is not None else [None] * len(pres)

    if doxy_var is not None:
        doxy = doxy_var.isel(N_PROF=i).values
        doxy_q_arr = doxy_qc[i, :] if doxy_qc is not None else [None] * len(doxy)
    else:
        doxy = doxy_q_arr = None

    if chla_var is not None:
        chla = chla_var.isel(N_PROF=i).values
        chla_q_arr = chla_qc[i, :] if chla_qc is not None else [None] * len(chla)
    else:
        chla = chla_q_arr = None

    if nitrate_var is not None:
        nitrate = nitrate_var.isel(N_PROF=i).values
        nitrate_q_arr = nitrate_qc[i, :] if nitrate_qc is not None else [None] * len(nitrate)
    else:
        nitrate = nitrate_q_arr = None

    if ph_var is not None:
        ph = ph_var.isel(N_PROF=i).values
        ph_q_arr = ph_qc[i, :] if ph_qc is not None else [None] * len(ph)
    else:
        ph = ph_q_arr = None

    return {
        "pres": pres,
        "pres_q_arr": pres_q_arr,
        "doxy": doxy,
        "doxy_q_arr": doxy_q_arr,
        "chla": chla,
        "chla_q_arr": chla_q_arr,
        "nitrate": nitrate,
        "nitrate_q_arr": nitrate_q_arr,
        "ph": ph,
        "ph_q_arr": ph_q_arr,
    }


def _merge_bgc_into_existing_profile(
    conn,
    profile_id: int,
    pres_src: str,
    doxy_src: Optional[str],
    chla_src: Optional[str],
    nitrate_src: Optional[str],
    ph_src: Optional[str],
    bgc_arrays: Dict[str, Any],
) -> None:
    """
    Core-preserving merge:

    - Fetch existing measurement rows (with T/S) for this profile.
    - For each BGC level, find nearest core level by pressure
      within PRESSURE_MATCH_TOL.
    - UPDATE those measurement rows to add BGC columns (DOXY, CHLA,
      NITRATE, pH + QC).
    - Never delete or overwrite T/S values.
    """
    rows = conn.execute(
        text(
            """
        SELECT measurement_id, pressure_dbar
        FROM measurements
        WHERE profile_id = :pid
        ORDER BY pressure_dbar
        """
        ),
        {"pid": profile_id},
    ).fetchall()

    if not rows:
        print(f"      ! No existing measurements for profile_id={profile_id}, skipping BGC merge.")
        return

    core_ids = np.array([r[0] for r in rows], dtype=int)
    core_pres = np.array([r[1] for r in rows], dtype=float)

    # Mask invalid core pressures
    core_valid = np.isfinite(core_pres)
    if not core_valid.any():
        print(f"      ! All core pressures NaN for profile_id={profile_id}, skipping BGC merge.")
        return

    pres = bgc_arrays["pres"]
    pres_q_arr = bgc_arrays["pres_q_arr"]

    doxy = bgc_arrays["doxy"]
    doxy_q_arr = bgc_arrays["doxy_q_arr"]
    chla = bgc_arrays["chla"]
    chla_q_arr = bgc_arrays["chla_q_arr"]
    nitrate = bgc_arrays["nitrate"]
    nitrate_q_arr = bgc_arrays["nitrate_q_arr"]
    ph = bgc_arrays["ph"]
    ph_q_arr = bgc_arrays["ph_q_arr"]

    updates: List[Dict[str, Any]] = []

    n_levels = len(pres)
    for idx in range(n_levels):
        p = pres[idx]

        # Skip nonsense pressure
        if not np.isfinite(p):
            continue

        # BGC values at this level
        d_val = doxy[idx] if doxy is not None else np.nan
        c_val = chla[idx] if chla is not None else np.nan
        n_val = nitrate[idx] if nitrate is not None else np.nan
        ph_val = ph[idx] if ph is not None else np.nan

        # If no BGC here, nothing to merge
        if np.isnan(d_val) and np.isnan(c_val) and np.isnan(n_val) and np.isnan(ph_val):
            continue

        # Find nearest valid core pressure
        diffs = np.abs(core_pres - p)
        diffs[~core_valid] = np.inf
        j = int(diffs.argmin())
        dp = float(diffs[j])

        if not np.isfinite(dp) or dp > PRESSURE_MATCH_TOL:
            # No good core level to attach this BGC level to
            continue

        mid = int(core_ids[j])

        # QC flags
        pq = pres_q_arr[idx] if pres_q_arr is not None else None
        d_q = doxy_q_arr[idx] if (doxy_q_arr is not None and not np.isnan(d_val)) else None
        c_q = chla_q_arr[idx] if (chla_q_arr is not None and not np.isnan(c_val)) else None
        n_q = nitrate_q_arr[idx] if (nitrate_q_arr is not None and not np.isnan(n_val)) else None
        ph_qv = ph_q_arr[idx] if (ph_q_arr is not None and not np.isnan(ph_val)) else None

        updates.append(
            {
                "mid": mid,
                "doxy_umol_kg": float(d_val) if not np.isnan(d_val) else None,
                "doxy_source": doxy_src,
                "doxy_qc": int(d_q) if d_q is not None else None,
                "chlorophyll_mg_m3": float(c_val) if not np.isnan(c_val) else None,
                "chla_source": chla_src,
                "chla_qc": int(c_q) if c_q is not None else None,
                "nitrate_umol_kg": float(n_val) if not np.isnan(n_val) else None,
                "nitrate_source": nitrate_src,
                "nitrate_qc": int(n_q) if n_q is not None else None,
                "ph_total": float(ph_val) if not np.isnan(ph_val) else None,
                "ph_source": ph_src,
                "ph_qc": int(ph_qv) if ph_qv is not None else None,
            }
        )

    if not updates:
        print(f"      ! No BGC values could be matched for profile_id={profile_id}.")
        return

    conn.execute(
        text(
            """
        UPDATE measurements
        SET
            doxy_umol_kg        = :doxy_umol_kg,
            doxy_source         = :doxy_source,
            doxy_qc             = :doxy_qc,
            chlorophyll_mg_m3   = :chlorophyll_mg_m3,
            chla_source         = :chla_source,
            chla_qc             = :chla_qc,
            nitrate_umol_kg     = :nitrate_umol_kg,
            nitrate_source      = :nitrate_source,
            nitrate_qc          = :nitrate_qc,
            ph_total            = :ph_total,
            ph_source           = :ph_source,
            ph_qc               = :ph_qc
        WHERE measurement_id = :mid
        """
        ),
        updates,
    )

    print(f"      → Updated {len(updates)} measurements with BGC for profile_id={profile_id}.")


# ----------------------------------------------------
# Main per-file ingestion
# ----------------------------------------------------
def ingest_bgc_file(nc_path: Path, dac: str) -> None:
    print(f"\n📄 Ingesting BGC file: {nc_path}")
    ds = xr.open_dataset(nc_path)

    # Float ID from PLATFORM_NUMBER or from filename
    if "PLATFORM_NUMBER" in ds:
        float_id = str(ds["PLATFORM_NUMBER"].values[0]).strip()
    else:
        base = nc_path.name.split("_")[0]
        # BGC names often like BR590XXXX / BD590XXXX
        float_id = base.lstrip("BRD")
    n_prof = ds.dims.get("N_PROF", 1)
    print(f"   float_id={float_id}, N_PROF={n_prof}")

    # Upsert float row
    with engine.begin() as conn:
        conn.execute(
            text(
                """
            INSERT INTO floats (float_id, dac, ocean, platform_type)
            VALUES (:float_id, :dac, :ocean, :platform_type)
            ON CONFLICT (float_id) DO UPDATE
              SET dac = EXCLUDED.dac;
            """
            ),
            {
                "float_id": float_id,
                "dac": dac,
                "ocean": "IO",  # keep consistent with ingest_core
                "platform_type": "ARGO",
            },
        )

    # Main variables
    lat_var = ds["LATITUDE"]
    lon_var = ds["LONGITUDE"]
    juld_var = ds["JULD"] if "JULD" in ds else None
    cyc_var = ds["CYCLE_NUMBER"] if "CYCLE_NUMBER" in ds else None
    data_mode_var = ds["DATA_MODE"] if "DATA_MODE" in ds else None

    # Core vars (we at least need PRES from BGC file for alignment)
    pres_var, pres_src, pres_qc = pick_var_with_source(ds, "PRES")

    # TEMP / PSAL may be missing in some BGC files (e.g. only TEMP_DOXY)
    try:
        temp_var, temp_src, temp_qc = pick_var_with_source(ds, "TEMP")
    except KeyError:
        temp_var = temp_src = temp_qc = None

    try:
        psal_var, psal_src, psal_qc = pick_var_with_source(ds, "PSAL")
    except KeyError:
        psal_var = psal_src = psal_qc = None

    # BGC vars
    doxy_var = chla_var = nitrate_var = ph_var = None
    doxy_src = chla_src = nitrate_src = ph_src = None
    doxy_qc = chla_qc = nitrate_qc = ph_qc = None

    if "DOXY" in ds:
        doxy_var, doxy_src, doxy_qc = pick_var_with_source(ds, "DOXY")
    if "CHLA" in ds:
        chla_var, chla_src, chla_qc = pick_var_with_source(ds, "CHLA")
    if "NITRATE" in ds:
        nitrate_var, nitrate_src, nitrate_qc = pick_var_with_source(ds, "NITRATE")
    if "PH_IN_SITU_TOTAL" in ds:
        ph_var, ph_src, ph_qc = pick_var_with_source(ds, "PH_IN_SITU_TOTAL")

    with engine.begin() as conn:
        for i in range(n_prof):
            lat = float(lat_var.values[i])
            lon = float(lon_var.values[i])
            profile_time = juld_to_timestamp(juld_var.values[i]) if juld_var is not None else None
            cycle_number = int(cyc_var.values[i]) if cyc_var is not None else i
            data_mode = _decode_data_mode(data_mode_var, i)

            # Try to find an existing core profile
            existing = conn.execute(
                text(
                    """
                SELECT profile_id
                FROM profiles
                WHERE float_id = :float_id
                  AND cycle_number = :cycle_number
                  AND profile_time IS NOT DISTINCT FROM :profile_time
                LIMIT 1;
                """
                ),
                {
                    "float_id": float_id,
                    "cycle_number": cycle_number,
                    "profile_time": profile_time,
                },
            ).fetchone()

            if existing:
                profile_id = existing[0]
                print(
                    f"   → MERGE BGC into existing core profile_id={profile_id} "
                    f"(float={float_id}, cycle={cycle_number})"
                )

                # Update profile metadata and set has_bgc = TRUE
                conn.execute(
                    text(
                        """
                    UPDATE profiles
                    SET latitude = :lat,
                        longitude = :lon,
                        position_geom = ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
                        data_mode = :data_mode,
                        has_bgc = TRUE
                    WHERE profile_id = :pid;
                    """
                    ),
                    {
                        "pid": profile_id,
                        "lat": lat,
                        "lon": lon,
                        "data_mode": data_mode,
                    },
                )

                # Extract BGC arrays for this profile and merge into existing measurements
                bgc_arrays = _extract_bgc_arrays_for_profile(
                    ds,
                    i,
                    pres_var,
                    doxy_var,
                    chla_var,
                    nitrate_var,
                    ph_var,
                    pres_qc,
                    doxy_qc,
                    chla_qc,
                    nitrate_qc,
                    ph_qc,
                )
                _merge_bgc_into_existing_profile(
                    conn,
                    profile_id,
                    pres_src,
                    doxy_src,
                    chla_src,
                    nitrate_src,
                    ph_src,
                    bgc_arrays,
                )

            else:
                # No core profile exists → create a new profile and insert full T/S + BGC rows
                result = conn.execute(
                    text(
                        """
                    INSERT INTO profiles (
                        float_id, cycle_number, profile_time,
                        latitude, longitude, position_geom,
                        data_mode, has_bgc
                    )
                    VALUES (
                        :float_id, :cycle_number, :profile_time,
                        :lat, :lon, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
                        :data_mode, TRUE
                    )
                    RETURNING profile_id;
                    """
                    ),
                    {
                        "float_id": float_id,
                        "cycle_number": cycle_number,
                        "profile_time": profile_time,
                        "lat": lat,
                        "lon": lon,
                        "data_mode": data_mode,
                    },
                )
                profile_id = result.scalar_one()
                print(f"   → NEW BGC-only profile_id={profile_id}, cycle={cycle_number}")

                # Insert full measurements (T/S + BGC) for this profile
                pres = pres_var.isel(N_PROF=i).values

                if temp_var is not None:
                    temp = temp_var.isel(N_PROF=i).values
                    temp_q_arr = temp_qc[i, :] if temp_qc is not None else [None] * len(temp)
                else:
                    temp = np.full_like(pres, np.nan, dtype=float)
                    temp_q_arr = [None] * len(pres)

                if psal_var is not None:
                    psal = psal_var.isel(N_PROF=i).values
                    psal_q_arr = psal_qc[i, :] if psal_qc is not None else [None] * len(psal)
                else:
                    psal = np.full_like(pres, np.nan, dtype=float)
                    psal_q_arr = [None] * len(pres)

                pres_q_arr = pres_qc[i, :] if pres_qc is not None else [None] * len(pres)

                if doxy_var is not None:
                    doxy = doxy_var.isel(N_PROF=i).values
                    doxy_q_arr = doxy_qc[i, :] if doxy_qc is not None else [None] * len(doxy)
                else:
                    doxy = doxy_q_arr = None

                if chla_var is not None:
                    chla = chla_var.isel(N_PROF=i).values
                    chla_q_arr = chla_qc[i, :] if chla_qc is not None else [None] * len(chla)
                else:
                    chla = chla_q_arr = None

                if nitrate_var is not None:
                    nitrate = nitrate_var.isel(N_PROF=i).values
                    nitrate_q_arr = nitrate_qc[i, :] if nitrate_qc is not None else [None] * len(
                        nitrate
                    )
                else:
                    nitrate = nitrate_q_arr = None

                if ph_var is not None:
                    ph = ph_var.isel(N_PROF=i).values
                    ph_q_arr = ph_qc[i, :] if ph_qc is not None else [None] * len(ph)
                else:
                    ph = ph_q_arr = None

                rows: List[Dict[str, Any]] = []
                n_levels = len(pres)

                for idx in range(n_levels):
                    p = pres[idx]
                    t = temp[idx]
                    s = psal[idx]

                    # If even PRES is NaN, row is useless
                    if np.isnan(p) and np.isnan(t) and np.isnan(s):
                        continue

                    pq = pres_q_arr[idx]
                    tq = temp_q_arr[idx]
                    sq = psal_q_arr[idx]

                    d_val = doxy[idx] if doxy is not None else np.nan
                    c_val = chla[idx] if chla is not None else np.nan
                    n_val = nitrate[idx] if nitrate is not None else np.nan
                    ph_val = ph[idx] if ph is not None else np.nan

                    d_q = doxy_q_arr[idx] if doxy_q_arr is not None else None
                    c_q = chla_q_arr[idx] if chla_q_arr is not None else None
                    n_q = nitrate_q_arr[idx] if nitrate_q_arr is not None else None
                    ph_qv = ph_q_arr[idx] if ph_q_arr is not None else None

                    rows.append(
                        {
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
                            "doxy_umol_kg": float(d_val) if not np.isnan(d_val) else None,
                            "doxy_source": doxy_src,
                            "doxy_qc": int(d_q) if d_q is not None else None,
                            "chlorophyll_mg_m3": float(c_val) if not np.isnan(c_val) else None,
                            "chla_source": chla_src,
                            "chla_qc": int(c_q) if c_q is not None else None,
                            "nitrate_umol_kg": float(n_val) if not np.isnan(n_val) else None,
                            "nitrate_source": nitrate_src,
                            "nitrate_qc": int(n_q) if n_q is not None else None,
                            "ph_total": float(ph_val) if not np.isnan(ph_val) else None,
                            "ph_source": ph_src,
                            "ph_qc": int(ph_qv) if ph_qv is not None else None,
                        }
                    )

                if rows:
                    conn.execute(
                        text(
                            """
                        INSERT INTO measurements (
                            profile_id,
                            pressure_dbar, pressure_source, pressure_qc,
                            depth_m,
                            temperature_c, temperature_source, temperature_qc,
                            salinity_psu, salinity_source, salinity_qc,
                            doxy_umol_kg, doxy_source, doxy_qc,
                            chlorophyll_mg_m3, chla_source, chla_qc,
                            nitrate_umol_kg, nitrate_source, nitrate_qc,
                            ph_total, ph_source, ph_qc
                        )
                        VALUES (
                            :profile_id,
                            :pressure_dbar, :pressure_source, :pressure_qc,
                            :depth_m,
                            :temperature_c, :temperature_source, :temperature_qc,
                            :salinity_psu, :salinity_source, :salinity_qc,
                            :doxy_umol_kg, :doxy_source, :doxy_qc,
                            :chlorophyll_mg_m3, :chla_source, :chla_qc,
                            :nitrate_umol_kg, :nitrate_source, :nitrate_qc,
                            :ph_total, :ph_source, :ph_qc
                        );
                        """
                        ),
                        rows,
                    )


# ----------------------------------------------------
# Root walker
# ----------------------------------------------------
def ingest_bgc_root(root: Path) -> None:
    from tqdm import tqdm

    files: List[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        for fname in filenames:
            if not fname.endswith(".nc"):
                continue
            files.append(Path(dirpath) / fname)

    print(f"Found {len(files)} BGC NetCDF files under {root}.")
    for path in tqdm(files, desc="BGC ingest"):
        # Expect path like .../dac/<dac>/<wmo>/profiles/file.nc
        # dac name is usually 3 levels up from file
        try:
            dac = path.parts[-4]
        except IndexError:
            dac = "unknown"

        try:
            ingest_bgc_file(path, dac=dac)
        except Exception as e:
            print(f"❌ Error ingesting {path}: {e}")


if __name__ == "__main__":
    ingest_bgc_root(BGC_ROOT)
