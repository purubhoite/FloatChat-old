# backend/api.py

from typing import Any, Dict, Optional

import base64
import io

import pandas as pd
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .ai_pipeline import answer_question
from .mcp_tools import tool_describe_dataframe, build_schema_from_df, tool_infer_viz_intent

app = FastAPI(title="FloatChat Backend API")

# CORS so Dash frontend can call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # for local dev; tighten later if needed
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root() -> Dict[str, str]:
    return {"message": "FloatChat backend alive"}


@app.post("/upload_nc")
def upload_nc_api(payload: Dict[str, Any]) -> Dict[str, Any]:
  """Upload a NetCDF file (as base64 string) and return full data extraction.

  Expects JSON:
    {
    "filename": "file.nc",
    "contents": "data:...;base64,AAAA..."  # Dash dcc.Upload format
    }

  Returns a JSON shape:
    {
    "ok": bool,
    "filename": str,
    "variables": ["temp", "salinity", ...],
    "dims": {"time": 100, "depth": 50, ...},
    "coords": {"time": {...}, "depth": {...}, ...},
    "time": {"var": "time", "min": "...", "max": "..."} | null,
    "depth": {"var": "depth", "min": float, "max": float} | null,
    "lat": {"var": "latitude", "min": float, "max": float} | null,
    "lon": {"var": "longitude", "min": float, "max": float} | null,
    "data": {
      "rows": [{...}, {...}, ...],  # Flattened data rows
      "summary": {...},  # Statistics per variable
      "schema": {...}    # Column information
    },
    "summary_text": "Human readable summary...",
    "error": str | null
    }
  """
  filename: str = (payload.get("filename") or "uploaded.nc").strip()
  contents: Optional[str] = payload.get("contents")

  if not contents:
    return {"ok": False, "filename": filename, "error": "No contents provided."}

  # Dash dcc.Upload sends "data:...;base64,<data>"; split off header if present
  try:
    if "," in contents:
      _, b64_data = contents.split(",", 1)
    else:
      b64_data = contents
    raw_bytes = base64.b64decode(b64_data)
  except Exception as e:
    return {
      "ok": False,
      "filename": filename,
      "error": f"Failed to decode base64 contents: {e}",
    }

  try:
    import xarray as xr  # type: ignore
    import numpy as np  # type: ignore

    with xr.open_dataset(io.BytesIO(raw_bytes)) as ds:
      # Load data into memory
      ds.load()

      variables = list(ds.data_vars.keys())
      dims = {k: int(v) for k, v in ds.dims.items()}
      coords_info = {}

      # Extract coordinate information
      for coord_name in ds.coords:
        try:
          coord_vals = ds.coords[coord_name].values
          if coord_vals.size > 0:
            coords_info[coord_name] = {
              "size": int(coord_vals.size),
              "dtype": str(coord_vals.dtype),
            }
            # Add min/max for numeric types
            if np.issubdtype(coord_vals.dtype, np.number):
              coords_info[coord_name]["min"] = float(np.nanmin(coord_vals))
              coords_info[coord_name]["max"] = float(np.nanmax(coord_vals))
            elif np.issubdtype(coord_vals.dtype, np.datetime64):
              coords_info[coord_name]["min"] = str(np.min(coord_vals))
              coords_info[coord_name]["max"] = str(np.max(coord_vals))
        except Exception:
          continue

      # Heuristic detection of key variables
      time_info = None
      depth_info = None
      lat_info = None
      lon_info = None

      # Find time variable
      for name in list(ds.coords.keys()) + list(ds.data_vars.keys()):
        if "time" in name.lower():
          try:
            vals = ds[name].values
            if vals.size > 0:
              t_min = np.min(vals)
              t_max = np.max(vals)
              time_info = {
                "var": name,
                "min": str(np.datetime_as_string(t_min, unit="s"))
                if np.issubdtype(t_min.dtype, np.datetime64)
                else str(t_min),
                "max": str(np.datetime_as_string(t_max, unit="s"))
                if np.issubdtype(t_max.dtype, np.datetime64)
                else str(t_max),
                "count": int(vals.size),
              }
          except Exception:
            time_info = None
          break

      # Find depth variable (depth / pres / pressure)
      depth_candidates = [
        name
        for name in list(ds.coords.keys()) + list(ds.data_vars.keys())
        if any(k in name.lower() for k in ["depth", "pres", "pressure"])
      ]
      for name in depth_candidates:
        try:
          vals = ds[name].values.astype(float)
          if vals.size > 0:
            d_min = float(np.nanmin(vals))
            d_max = float(np.nanmax(vals))
            depth_info = {"var": name, "min": d_min, "max": d_max, "count": int(vals.size)}
            break
        except Exception:
          continue

      # Find latitude variable
      for name in list(ds.coords.keys()) + list(ds.data_vars.keys()):
        if "lat" in name.lower():
          try:
            vals = ds[name].values.astype(float)
            if vals.size > 0:
              lat_info = {
                "var": name,
                "min": float(np.nanmin(vals)),
                "max": float(np.nanmax(vals)),
              }
          except Exception:
            pass
          break

      # Find longitude variable
      for name in list(ds.coords.keys()) + list(ds.data_vars.keys()):
        if "lon" in name.lower():
          try:
            vals = ds[name].values.astype(float)
            if vals.size > 0:
              lon_info = {
                "var": name,
                "min": float(np.nanmin(vals)),
                "max": float(np.nanmax(vals)),
              }
          except Exception:
            pass
          break

      # ----------------------------------------------------------------
      # EXTRACT ALL DATA: Convert xarray Dataset to pandas DataFrame
      # ----------------------------------------------------------------
      try:
        # Convert to dataframe - this flattens the dataset
        df = ds.to_dataframe().reset_index()
        
        # Handle datetime columns for JSON serialization
        for col in df.columns:
          if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].astype(str)
        
        # Limit rows if dataset is very large (to prevent memory issues)
        MAX_ROWS = 10000
        total_rows = len(df)
        if total_rows > MAX_ROWS:
          df = df.head(MAX_ROWS)
          truncated = True
        else:
          truncated = False
        
        # Convert to rows format
        rows = df.to_dict(orient="records")
        
        # Build summary statistics for each numeric variable
        summary = {
          "total_rows": total_rows,
          "returned_rows": len(rows),
          "truncated": truncated,
          "variables": {}
        }
        
        for var in variables:
          if var in df.columns:
            try:
              col_data = pd.to_numeric(df[var], errors='coerce')
              if col_data.notna().any():
                summary["variables"][var] = {
                  "min": float(col_data.min()),
                  "max": float(col_data.max()),
                  "mean": float(col_data.mean()),
                  "count": int(col_data.notna().sum()),
                  "missing": int(col_data.isna().sum()),
                }
            except Exception:
              continue
        
        # Build schema
        schema = {
          "columns": [
            {"name": col, "dtype": str(df[col].dtype)}
            for col in df.columns
          ]
        }
        
        data_payload = {
          "rows": rows,
          "summary": summary,
          "schema": schema,
        }
        
      except Exception as data_err:
        # If data extraction fails, return metadata only
        data_payload = {
          "rows": None,
          "summary": {"error": str(data_err)},
          "schema": {"columns": []},
        }

  except Exception as e:
    return {
      "ok": False,
      "filename": filename,
      "error": f"Failed to read NetCDF file: {e}",
    }

  # Build human-readable summary text for LLM context
  parts = [f"NetCDF file '{filename}' uploaded successfully."]
  if variables:
    parts.append(f"Contains {len(variables)} variables: " + ", ".join(variables[:10]) + (" ..." if len(variables) > 10 else ""))
  if dims:
    dim_str = ", ".join(f"{k}={v}" for k, v in dims.items())
    parts.append(f"Dimensions: {dim_str}.")
  if time_info:
    parts.append(
      f"Time range ({time_info['var']}): {time_info['min']} to {time_info['max']} ({time_info.get('count', 'N/A')} points)."
    )
  if depth_info:
    parts.append(
      f"Depth range ({depth_info['var']}): {depth_info['min']:.1f} to {depth_info['max']:.1f}."
    )
  if lat_info and lon_info:
    parts.append(
      f"Geographic extent: Lat [{lat_info['min']:.2f}, {lat_info['max']:.2f}], Lon [{lon_info['min']:.2f}, {lon_info['max']:.2f}]."
    )
  if data_payload.get("rows"):
    parts.append(f"Extracted {len(data_payload['rows'])} data rows for visualization.")

  summary_text = " ".join(parts)

  return {
    "ok": True,
    "filename": filename,
    "variables": variables,
    "dims": dims,
    "coords": coords_info,
    "time": time_info,
    "depth": depth_info,
    "lat": lat_info,
    "lon": lon_info,
    "data": data_payload,
    "summary_text": summary_text,
    "error": None,
  }


@app.post("/ask")
def ask_api(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main endpoint called by the Dash frontend.

    Expects JSON:
      { 
        "query": "<user text>",
        "conversation_history": [  # optional: previous messages for context
          {"role": "user", "text": "..."},
          {"role": "assistant", "text": "..."},
          ...
        ]
      }

    Returns a JSON shape:

      {
        "ok": bool,
        "explanation": str,
        "sql": str | null,
        "error": str | null,
        "data": {
          "rows": [ ... ],
          "summary": { ... },
          "schema": { ... }
        },
        "viz": { ... },
        "history": [...]
      }
    """
    user_query: str = (payload.get("query") or "").strip()
    conversation_history: list = payload.get("conversation_history", [])
    
    if not user_query:
        return {
            "ok": False,
            "mode": "error",
            "explanation": "Empty query.",
            "sql": None,
            "error": "Empty query.",
            "plan": None,
            "data": {
                "rows": None,
                "summary": {"empty": True},
                "schema": {"columns": []},
            },
            "viz": None,
            "history": [],
        }

    result = answer_question(user_query, conversation_history=conversation_history)

    df: Optional[pd.DataFrame] = result.get("df")
    if isinstance(df, pd.DataFrame) and not df.empty:
        rows = df.to_dict(orient="records")
        summary = tool_describe_dataframe(df)
        schema = build_schema_from_df(df)
        viz = tool_infer_viz_intent(df, result.get("final_sql") or "", user_query)
    else:
        rows = None
        summary = {"empty": True}
        schema = {"columns": []}
        viz = None

    return {
        "ok": result.get("ok", False),
        "mode": result.get("mode", "sql"),
        "explanation": result.get("final_explanation"),
        "sql": result.get("final_sql"),
        "error": result.get("error"),
        "plan": result.get("plan"),
        "data": {
            "rows": rows,
            "summary": summary,
            "schema": schema,
        },
        "viz": viz,
        "history": result.get("history", []),
    }
