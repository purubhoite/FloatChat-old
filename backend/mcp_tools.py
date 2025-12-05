# backend/mcp_tools.py

from typing import Dict, Any, List

import pandas as pd

from .sql_guard import run_user_sql


def tool_run_sql(sql: str) -> pd.DataFrame:
    """
    MCP-style tool that executes a validated, read-only SQL query
    against the Indian Ocean ARGO + BGC database.

    Under the hood this uses sql_guard.run_user_sql(), which:
      - enforces SELECT/WITH only,
      - blocks dangerous keywords (INSERT, DROP, etc.),
      - clamps / injects a LIMIT for safety.
    """
    return run_user_sql(sql)


def tool_build_region_filter(name: str) -> str:
    """
    Return a SQL predicate (WHERE-clause fragment) for a named region.
    This is meant for the LLM to reuse in generated SQL.

    Examples of returned strings:
      - "latitude BETWEEN 5 AND 25 AND longitude BETWEEN 45 AND 80"
      - "latitude BETWEEN -5 AND 5"
      - "TRUE"  (fallback)
    """
    n = (name or "").lower()

    if "arabian" in n:
        # Approximate Arabian Sea bounding box
        return "latitude BETWEEN 5 AND 25 AND longitude BETWEEN 45 AND 80"

    if "bay of bengal" in n or "bengal" in n:
        return "latitude BETWEEN 5 AND 25 AND longitude BETWEEN 80 AND 100"

    if "equator" in n or "equatorial" in n:
        return "latitude BETWEEN -5 AND 5 AND longitude BETWEEN 20 AND 120"

    # Fallback: no spatial constraint
    return "TRUE"


def tool_describe_dataframe(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Summarize a query result DataFrame for the LLM.

    Returns a JSON-serializable dict with:
      - time_min / time_max if 'profile_time' present
      - basic statistics (min, max, mean, etc.) for numeric columns

    This is used in ai_pipeline.answer_question() so the LLM can
    explain the result in plain language.
    """
    summary: Dict[str, Any] = {}

    if df is None or df.empty:
        summary["empty"] = True
        return summary

    # Time coverage, if present
    if "profile_time" in df.columns:
        summary["time_min"] = str(df["profile_time"].min())
        summary["time_max"] = str(df["profile_time"].max())

    # Numeric statistics
    numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
    if numeric_cols:
        stats = df[numeric_cols].describe().to_dict()
        summary["stats"] = stats
    else:
        summary["stats"] = {}

    return summary


# --------------------------------------------------------------------
# NEW HELPERS: schema + visualization intent
# --------------------------------------------------------------------

def build_schema_from_df(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Build a simple schema description for the frontend.

    Returns:
      {
        "columns": [
          {"name": "...", "dtype": "...", "role": "..."},
          ...
        ]
      }
    """
    schema: Dict[str, Any] = {"columns": []}
    if df is None or df.empty:
        return schema

    # Simple role inference based on column name
    def infer_role(col: str) -> str:
        lc = col.lower()
        if lc in ("profile_id",):
            return "profile_id"
        if lc in ("float_id", "platform_number"):
            return "float_id"
        if "time" in lc or "date" in lc or lc == "juld":
            return "time"
        if lc == "latitude":
            return "latitude"
        if lc == "longitude":
            return "longitude"
        if lc in ("depth_m", "pres", "pressure_dbar"):
            return "depth"
        if lc.startswith("temp"):
            return "temperature"
        if lc.startswith("sal") or "salinity" in lc:
            return "salinity"
        if "doxy" in lc:
            return "oxygen"
        if "chla" in lc or "chlorophyll" in lc:
            return "chlorophyll"
        if "nitrate" in lc:
            return "nitrate"
        if lc.startswith("ph"):
            return "ph"
        return "value"

    for col in df.columns:
        dtype = str(df[col].dtype)
        role = infer_role(col)
        schema["columns"].append(
            {
                "name": col,
                "dtype": dtype,
                "role": role,
            }
        )

    return schema


def tool_infer_viz_intent(df: pd.DataFrame, sql: str = "", user_query: str = "") -> Dict[str, Any]:
    """
    Infer a simple visualization intent from the DataFrame + context.

    Returns a dict like:
      {
        "kind": "map" | "profile_plot" | "time_series" | "depth_time" | "table",
        "level": "measurement" | "profile" | "float",
        "variables": [...],
        "x": "...",
        "y": "...",
        "group_by": [...],
        "spatial": bool,
        "primary_variable": "..."
      }
    """
    intent: Dict[str, Any] = {
        "kind": "table",
        "level": "profile",
        "variables": [],
        "x": None,
        "y": None,
        "group_by": [],
        "spatial": False,
        "primary_variable": None,
    }

    if df is None or df.empty:
        return intent

    cols = set(df.columns)

    # Candidate variables in priority order
    candidate_vars: List[str] = [
        "doxy_umol_kg",
        "chlorophyll_mg_m3",
        "nitrate_umol_kg",
        "ph_total",
        "temperature_c",
        "salinity_psu",
    ]
    present_vars = [c for c in candidate_vars if c in cols]
    intent["variables"] = present_vars
    if present_vars:
        intent["primary_variable"] = present_vars[0]

    has_latlon = "latitude" in cols and "longitude" in cols
    has_depth = "depth_m" in cols or "pressure_dbar" in cols
    has_time = "profile_time" in cols

    # Determine row "level"
    if has_depth:
        intent["level"] = "measurement"
    elif "profile_id" in cols:
        intent["level"] = "profile"
    elif "float_id" in cols:
        intent["level"] = "float"
    else:
        intent["level"] = "profile"

    # 1) Map: if we have location AND no obvious depth/time viz
    # (Map can always be combined with other views, so kind may still be profile_plot/time_series
    # but we set spatial flag here.)
    if has_latlon:
        intent["spatial"] = True

    # 2) Depth-time: depth + time + variable
    if has_depth and has_time and present_vars:
        intent["kind"] = "depth_time"
        intent["x"] = "profile_time"
        intent["y"] = "depth_m" if "depth_m" in cols else "pressure_dbar"
        return intent

    # 3) Profile plot: depth + variable
    if has_depth and present_vars:
        intent["kind"] = "profile_plot"
        intent["y"] = "depth_m" if "depth_m" in cols else "pressure_dbar"
        intent["x"] = present_vars[0]
        if "profile_id" in cols:
            intent["group_by"] = ["profile_id"]
        return intent

    # 4) Time-series: time + variable
    if has_time and present_vars:
        intent["kind"] = "time_series"
        intent["x"] = "profile_time"
        intent["y"] = present_vars[0]
        if "float_id" in cols:
            intent["group_by"] = ["float_id"]
        return intent

    # 5) Spatial table/map: lat/lon but no depth/var
    if has_latlon:
        intent["kind"] = "map"
        intent["x"] = "longitude"
        intent["y"] = "latitude"
        return intent

    # 6) Fallback: table only
    intent["kind"] = "table"
    return intent
