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
    Infer visualization intent from DataFrame + user query using keyword detection.
    
    Supports 9 ARGO visualization types:
    1. profile_plot - Vertical profile (variable vs depth)
    2. overlaid_profiles - Multiple cycles overlaid
    3. section_plot - Hovmöller/Section (depth vs time heatmap)
    4. ts_diagram - Temperature-Salinity diagram
    5. time_series - Variable over time
    6. map - Trajectory/location map
    7. comparison - Multi-float comparison
    8. density_plot - Sigma-theta/density structure
    9. table - Tabular data (fallback)

    Returns a dict with:
      {
        "primary_kind": str,     # Main visualization type
        "show_map": bool,        # Show map alongside
        "show_table": bool,      # Show table alongside
        "level": str,            # "measurement" | "profile" | "float"
        "variables": [...],      # Available variables
        "primary_variable": str, # Main variable to plot
        "depth_col": str | None, # "depth_m" or "pressure_dbar"
        "time_col": str | None,  # "profile_time" or None
        "n_profiles": int,       # Number of unique profiles
        "n_floats": int,         # Number of unique floats
        "has_ts_pair": bool,     # Both temp + sal present
        "is_bgc": bool,          # Has BGC variables
        "group_by": [...],       # Grouping columns
        "x": str | None,         # X-axis column
        "y": str | None,         # Y-axis column
    }
    """
    query_lower = (user_query or "").lower()
    
    # Initialize intent with defaults
    intent: Dict[str, Any] = {
        "primary_kind": "table",
        "show_map": False,
        "show_table": True,
        "level": "profile",
        "variables": [],
        "primary_variable": None,
        "depth_col": None,
        "time_col": None,
        "n_profiles": 0,
        "n_floats": 0,
        "has_ts_pair": False,
        "is_bgc": False,
        "group_by": [],
        "x": None,
        "y": None,
    }

    if df is None or df.empty:
        return intent

    cols = set(df.columns)
    
    # -------------------------------------------------------------------------
    # 1) Detect available columns and variables
    # -------------------------------------------------------------------------
    
    # Core physical variables
    core_vars: List[str] = ["temperature_c", "salinity_psu"]
    # BGC variables (priority order)
    bgc_vars: List[str] = ["doxy_umol_kg", "chlorophyll_mg_m3", "nitrate_umol_kg", "ph_total"]
    # All candidate variables
    all_candidate_vars: List[str] = bgc_vars + core_vars
    
    present_vars = [c for c in all_candidate_vars if c in cols]
    intent["variables"] = present_vars
    
    # Check for T-S pair
    has_temp = "temperature_c" in cols
    has_sal = "salinity_psu" in cols
    intent["has_ts_pair"] = has_temp and has_sal
    
    # Check for BGC
    present_bgc = [v for v in bgc_vars if v in cols]
    intent["is_bgc"] = len(present_bgc) > 0
    
    # Primary variable: prefer BGC, then core
    if present_vars:
        intent["primary_variable"] = present_vars[0]
    
    # Depth column
    if "depth_m" in cols:
        intent["depth_col"] = "depth_m"
    elif "pressure_dbar" in cols:
        intent["depth_col"] = "pressure_dbar"
    
    # Time column
    if "profile_time" in cols:
        intent["time_col"] = "profile_time"
    
    has_depth = intent["depth_col"] is not None
    has_time = intent["time_col"] is not None
    has_latlon = "latitude" in cols and "longitude" in cols
    
    # Count profiles and floats
    if "profile_id" in cols:
        intent["n_profiles"] = int(df["profile_id"].nunique())
    if "float_id" in cols:
        intent["n_floats"] = int(df["float_id"].nunique())
    
    # Determine row level
    if has_depth:
        intent["level"] = "measurement"
    elif "profile_id" in cols:
        intent["level"] = "profile"
    elif "float_id" in cols:
        intent["level"] = "float"
    
    # Always show map if lat/lon present
    intent["show_map"] = has_latlon
    
    # -------------------------------------------------------------------------
    # 2) Keyword detection from user query
    # -------------------------------------------------------------------------
    
    # Profile keywords
    profile_kw = any(kw in query_lower for kw in [
        "profile", "vertical", "with depth", "vs depth", "against depth"
    ])
    
    # Time-series / trend keywords
    timeseries_kw = any(kw in query_lower for kw in [
        "trend", "over time", "change over", "last 6 months", "last year",
        "past year", "monthly", "seasonal", "evolution", "surface"
    ])
    
    # Section / Hovmöller keywords
    section_kw = any(kw in query_lower for kw in [
        "section", "hovmöller", "hovmoller", "depth-time", "depth time",
        "variation", "from", "to"  # e.g., "from Jan to April"
    ])
    
    # T-S diagram keywords
    ts_kw = any(kw in query_lower for kw in [
        "t-s", "ts diagram", "t–s", "temperature-salinity", "temperature salinity",
        "water mass", "water masses", "density", "sigma", "stratification",
        "mixing", "relationship between temperature and salinity"
    ])
    
    # Comparison keywords
    compare_kw = any(kw in query_lower for kw in [
        "compare", "comparison", "vs", "versus", "difference", "differ",
        "contrast", "between"
    ])
    
    # Location / trajectory keywords
    location_kw = any(kw in query_lower for kw in [
        "where", "location", "trajectory", "trajectories", "near", "closest",
        "position", "moved", "drift"
    ])
    
    # Overlaid / multiple profile keywords
    overlaid_kw = any(kw in query_lower for kw in [
        "overlay", "overlaid", "multiple profiles", "all profiles", "last 5",
        "last 10", "compare profiles", "profiles over"
    ])
    
    # -------------------------------------------------------------------------
    # 3) Decision logic based on data + keywords
    # -------------------------------------------------------------------------
    
    # Priority 1: T-S Diagram
    # Show when: both temp + sal exist AND t-s keywords detected
    if intent["has_ts_pair"] and ts_kw:
        intent["primary_kind"] = "ts_diagram"
        intent["x"] = "salinity_psu"
        intent["y"] = "temperature_c"
        if "profile_id" in cols:
            intent["group_by"] = ["profile_id"]
        return intent
    
    # Priority 2: Multi-float comparison
    # Show when: compare keywords AND multiple floats
    if compare_kw and intent["n_floats"] >= 2 and present_vars:
        intent["primary_kind"] = "comparison"
        intent["y"] = intent["depth_col"]
        intent["x"] = intent["primary_variable"]
        intent["group_by"] = ["float_id"]
        return intent

    # Priority 3: Overlaid profiles (Explicit or specialized)
    # Show when: depth + variable + multiple profiles + (overlaid keywords OR profile keywords)
    # logic: if user says "profiles" we should show profiles, not a section
    if has_depth and present_vars and intent["n_profiles"] > 1:
        if overlaid_kw or profile_kw:
            intent["primary_kind"] = "overlaid_profiles"
            intent["y"] = intent["depth_col"]
            intent["x"] = intent["primary_variable"]
            if "profile_id" in cols:
                intent["group_by"] = ["profile_id"]
            return intent

    # Priority 4: Single vertical profile (Explicit)
    if has_depth and present_vars:
        if profile_kw or intent["n_profiles"] == 1:
            intent["primary_kind"] = "profile_plot"
            intent["y"] = intent["depth_col"]
            intent["x"] = intent["primary_variable"]
            if "profile_id" in cols:
                intent["group_by"] = ["profile_id"]
            return intent
    
    # Priority 5: Section / Hovmöller plot
    # Show when: depth + time + variable AND (section keywords OR time-series keywords)
    # Waited until after profile checks to avoid hijacking "salinity profiles"
    if has_depth and has_time and present_vars:
        if section_kw or timeseries_kw or (intent["n_profiles"] > 5 and not profile_kw):
            intent["primary_kind"] = "section_plot"
            intent["x"] = intent["time_col"]
            intent["y"] = intent["depth_col"]
            return intent
    
    # Priority 6: Time-series
    # Show when: time + variable + (trend keywords OR no depth)
    if has_time and present_vars:
        if timeseries_kw or not has_depth:
            intent["primary_kind"] = "time_series"
            intent["x"] = intent["time_col"]
            intent["y"] = intent["primary_variable"]
            if "float_id" in cols:
                intent["group_by"] = ["float_id"]
            return intent
    
    # Priority 7: Map-only
    # Show when: lat/lon present + location keywords + no depth/time viz needed
    if has_latlon and location_kw:
        intent["primary_kind"] = "map"
        intent["x"] = "longitude"
        intent["y"] = "latitude"
        return intent
    
    # Priority 8: Defaults (Fallbacks)
    
    # Default A: If > 1 profile and depth -> Overlaid
    if has_depth and present_vars and intent["n_profiles"] > 1:
        intent["primary_kind"] = "overlaid_profiles"
        intent["y"] = intent["depth_col"]
        intent["x"] = intent["primary_variable"]
        if "profile_id" in cols:
            intent["group_by"] = ["profile_id"]
        return intent

    # Default B: If time + depth -> Section
    if has_depth and has_time and present_vars:
        intent["primary_kind"] = "section_plot"
        intent["x"] = intent["time_col"]
        intent["y"] = intent["depth_col"]
        return intent
    
    # Default C: Profile plot
    if has_depth and present_vars:
        intent["primary_kind"] = "profile_plot"
        intent["y"] = intent["depth_col"]
        intent["x"] = intent["primary_variable"]
        if "profile_id" in cols:
            intent["group_by"] = ["profile_id"]
        return intent
    
    # Default D: Time series
    if has_time and present_vars:
        intent["primary_kind"] = "time_series"
        intent["x"] = intent["time_col"]
        intent["y"] = intent["primary_variable"]
        if "float_id" in cols:
            intent["group_by"] = ["float_id"]
        return intent
    
    # If we have lat/lon → map
    if has_latlon:
        intent["primary_kind"] = "map"
        intent["x"] = "longitude"
        intent["y"] = "latitude"
        return intent
    
    # Fallback: table only
    intent["primary_kind"] = "table"
    return intent
