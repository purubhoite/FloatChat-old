# backend/index_float_summaries.py

"""
Build / refresh float-level summaries in the RAG index.

Assumes your database has:
  - floats(float_id, platform_type, dac, ocean)
  - profiles(profile_id, float_id, profile_time, latitude, longitude, has_bgc, data_mode)
  - measurements(... temperature_c, salinity_psu, doxy_umol_kg,
                  chlorophyll_mg_m3, nitrate_umol_kg, ph_total ...)

We aggregate at float_id level and index summary texts as type="float_summary".
"""

from typing import List, Optional

import chromadb
import pandas as pd
from sqlalchemy import text

from .db import engine
from .embeddings import get_embedder
from .rag_index import VECTOR_STORE_DIR, COLLECTION_NAME


def fetch_float_aggregates(limit: Optional[int] = None) -> pd.DataFrame:
    """
    Fetch per-float aggregates from the database.
    You can tweak the WHERE clause to restrict to Indian Ocean, last 5 yrs, etc.
    """
    sql = """
        SELECT
          f.float_id,
          f.dac,
          f.platform_type,
          f.ocean,
          COUNT(DISTINCT p.profile_id)        AS n_profiles,
          MIN(p.profile_time)                 AS first_profile_time,
          MAX(p.profile_time)                 AS last_profile_time,
          MIN(p.latitude)                     AS min_lat,
          MAX(p.latitude)                     AS max_lat,
          MIN(p.longitude)                    AS min_lon,
          MAX(p.longitude)                    AS max_lon,
          BOOL_OR(p.has_bgc)                  AS has_bgc,

          MIN(m.temperature_c)                AS min_temp,
          MAX(m.temperature_c)                AS max_temp,
          MIN(m.salinity_psu)                 AS min_sal,
          MAX(m.salinity_psu)                 AS max_sal,

          MIN(m.doxy_umol_kg)                 AS min_doxy,
          MAX(m.doxy_umol_kg)                 AS max_doxy,
          MIN(m.chlorophyll_mg_m3)            AS min_chla,
          MAX(m.chlorophyll_mg_m3)            AS max_chla,
          MIN(m.nitrate_umol_kg)              AS min_no3,
          MAX(m.nitrate_umol_kg)              AS max_no3,
          MIN(m.ph_total)                     AS min_ph,
          MAX(m.ph_total)                     AS max_ph
        FROM floats f
        JOIN profiles p ON f.float_id = p.float_id
        JOIN measurements m ON p.profile_id = m.profile_id
        WHERE f.ocean = 'IO'
        GROUP BY f.float_id, f.dac, f.platform_type, f.ocean
        ORDER BY f.float_id
    """
    if limit is not None:
        sql += f" LIMIT {int(limit)}"

    with engine.begin() as conn:
        df = pd.read_sql(text(sql), conn)

    return df


def build_summary_row(row: pd.Series) -> str:
    """
    Turn one aggregate row into a short natural-language summary.
    """
    fid = row["float_id"]
    dac = row.get("dac") or "unknown DAC"
    n_prof = int(row["n_profiles"])

    t0 = row["first_profile_time"]
    t1 = row["last_profile_time"]

    time_span = ""
    if pd.notna(t0) and pd.notna(t1):
        time_span = f" from {str(t0.date())} to {str(t1.date())}"

    lat_span = f"{row['min_lat']:.1f} to {row['max_lat']:.1f}"
    lon_span = f"{row['min_lon']:.1f} to {row['max_lon']:.1f}"

    # Core variables
    min_temp, max_temp = row["min_temp"], row["max_temp"]
    min_sal, max_sal = row["min_sal"], row["max_sal"]

    has_bgc = bool(row["has_bgc"])

    sentence = (
        f"Float {fid} (DAC: {dac}) has {n_prof} profiles in the Indian Ocean"
        f"{time_span}, spanning latitudes {lat_span} and longitudes {lon_span}. "
    )

    if pd.notna(min_temp) and pd.notna(max_temp):
        sentence += f"Temperature ranges from {min_temp:.1f} to {max_temp:.1f} °C. "
    if pd.notna(min_sal) and pd.notna(max_sal):
        sentence += f"Salinity ranges from {min_sal:.2f} to {max_sal:.2f} PSU. "

    if has_bgc:
        bgc_parts: List[str] = []
        if pd.notna(row["min_doxy"]) and pd.notna(row["max_doxy"]):
            bgc_parts.append(f"oxygen {row['min_doxy']:.1f}–{row['max_doxy']:.1f} µmol/kg")
        if pd.notna(row["min_chla"]) and pd.notna(row["max_chla"]):
            bgc_parts.append(f"chlorophyll {row['min_chla']:.2f}–{row['max_chla']:.2f} mg/m³")
        if pd.notna(row["min_no3"]) and pd.notna(row["max_no3"]):
            bgc_parts.append(f"nitrate {row['min_no3']:.1f}–{row['max_no3']:.1f} µmol/kg")
        if pd.notna(row["min_ph"]) and pd.notna(row["max_ph"]):
            bgc_parts.append(f"pH {row['min_ph']:.2f}–{row['max_ph']:.2f}")

        if bgc_parts:
            sentence += "BGC coverage includes " + ", ".join(bgc_parts) + ". "
        else:
            sentence += "This float has BGC profiles, but BGC parameter ranges are sparse. "
    else:
        sentence += "This float currently has only core (temperature/salinity) profiles ingested. "

    return sentence.strip()


def index_float_summaries(limit: Optional[int] = None) -> None:
    """
    Build embeddings for per-float summary texts and store them in Chroma
    with type="float_summary".
    """
    df = fetch_float_aggregates(limit=limit)
    if df.empty:
        print("⚠️ No float aggregates found; check your database / WHERE clause.")
        return

    client = chromadb.PersistentClient(path=VECTOR_STORE_DIR)
    collection = client.get_or_create_collection(COLLECTION_NAME)

    # Remove old float_summary docs only
    collection.delete(where={"type": "float_summary"})

    embed = get_embedder()

    ids: List[str] = []
    texts: List[str] = []
    metas: List[dict] = []
    embs: List[List[float]] = []

    for _, row in df.iterrows():
        fid = row["float_id"]
        text_summary = build_summary_row(row)

        doc_id = f"float_summary_{fid}"
        ids.append(doc_id)
        texts.append(text_summary)
        metas.append({"type": "float_summary", "float_id": fid})
        embs.append(embed(text_summary))

    collection.add(ids=ids, documents=texts, metadatas=metas, embeddings=embs)

    print(f"✅ Indexed {len(ids)} float summaries into RAG.")


if __name__ == "__main__":
    # You can pass a small limit during testing, e.g. 50
    index_float_summaries(limit=None)
