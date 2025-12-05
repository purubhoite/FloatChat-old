# backend/schema_docs.py

"""
Schema + documentation for the ARGO + BGC Indian Ocean database.

These constants are consumed by the RAG layer (rag_index.py, index_schema_docs.py)
and by the NL→SQL agent to generate correct, non-hallucinated queries.
"""

# ---------------------------------------------------------------------------
# 1. Human-readable schema overview
# ---------------------------------------------------------------------------

SCHEMA_TEXT = """
DATABASE OVERVIEW
==================

The database stores ARGO and BGC (biogeochemical) profile data for the Indian Ocean.
There are three main tables:

1) floats
---------
One row per platform (float / observing platform).

Columns:
- float_id        : VARCHAR, primary key. WMO / platform identifier (e.g. "2902209").
- dac             : VARCHAR, data assembly center (e.g. "coriolis").
- platform_type   : VARCHAR, type of platform (e.g. 'ARGO').
- ocean           : CHAR(2), coarse ocean basin code.
                    For Indian Ocean floats this is typically 'IO'.

IMPORTANT:
- floats.ocean is a **coarse basin label**, e.g. 'IO'.
  It is NOT used for sub-basins such as "Arabian Sea" or "Bay of Bengal".
  For those sub-regions you MUST use latitude/longitude filters on profiles.

2) profiles
-----------
One row per vertical profile.

Columns:
- profile_id      : INTEGER, primary key.
- float_id        : VARCHAR, foreign key → floats(float_id).
- cycle_number    : INTEGER, the float's profile number.
- profile_time    : TIMESTAMP, time of the profile (UTC).
- latitude        : DOUBLE PRECISION, profile latitude in degrees.
- longitude       : DOUBLE PRECISION, profile longitude in degrees.
- position_geom   : GEOMETRY(Point, 4326), PostGIS point for spatial queries.
- data_mode       : CHAR(1), overall data mode for the profile
                    (e.g., 'R' = real-time, 'A' = adjusted, etc.).
- has_bgc         : BOOLEAN, TRUE if any BGC variables (oxygen, nitrate, etc.)
                    are available in the measurements for this profile.

3) measurements
----------------
One row per depth/pressure level in a profile.

Columns:
- measurement_id      : INTEGER, primary key.
- profile_id          : INTEGER, foreign key → profiles(profile_id).

Core physical variables:
- pressure_dbar       : DOUBLE PRECISION, pressure in dbar.
- pressure_source     : VARCHAR, 'ADJUSTED' or 'RAW'.
- pressure_qc         : INTEGER, QC flag (1 = good, etc.).
- depth_m             : DOUBLE PRECISION, approximate depth in meters (often ~ pressure).
- temperature_c       : DOUBLE PRECISION, in situ temperature (°C).
- temperature_source  : VARCHAR, 'ADJUSTED' or 'RAW'.
- temperature_qc      : INTEGER, QC flag.
- salinity_psu        : DOUBLE PRECISION, practical salinity (PSU).
- salinity_source     : VARCHAR, 'ADJUSTED' or 'RAW'.
- salinity_qc         : INTEGER, QC flag.

BGC variables:
- doxy_umol_kg        : DOUBLE PRECISION, dissolved oxygen (µmol/kg).
- doxy_source         : VARCHAR, 'ADJUSTED' or 'RAW'.
- doxy_qc             : INTEGER, QC flag.
- chlorophyll_mg_m3   : DOUBLE PRECISION, chlorophyll-a (mg/m³).
- chla_source         : VARCHAR, 'ADJUSTED' or 'RAW'.
- chla_qc             : INTEGER, QC flag.
- nitrate_umol_kg     : DOUBLE PRECISION, nitrate (µmol/kg).
- nitrate_source      : VARCHAR, 'ADJUSTED' or 'RAW'.
- nitrate_qc          : INTEGER, QC flag.
- ph_total            : DOUBLE PRECISION, total pH (dimensionless).
- ph_source           : VARCHAR, 'ADJUSTED' or 'RAW'.
- ph_qc               : INTEGER, QC flag.

BASIC JOIN LOGIC
================

- profiles.float_id      → floats.float_id
- measurements.profile_id → profiles.profile_id

Typical FROM/JOIN pattern:

  FROM floats f
  JOIN profiles p   ON p.float_id   = f.float_id
  JOIN measurements m ON m.profile_id = p.profile_id

REGIONS AND SPATIAL LOGIC
=========================

The database focuses on the Indian Ocean. For sub-regions, use latitude/longitude
conditions or PostGIS spatial predicates on profiles.position_geom.

Approximate region definitions:

- Indian Ocean (broad): 
    * Use floats.ocean = 'IO'
      OR a coarse bounding box such as
        latitude BETWEEN -45 AND 30
        longitude BETWEEN 20 AND 120

- Arabian Sea:
    * Latitude between 0° and 30°N
    * Longitude between 45°E and 75°E

      WHERE
        p.latitude  BETWEEN 0  AND 30
        AND p.longitude BETWEEN 45 AND 75

    * Or, with PostGIS:

      ST_Contains(
        ST_MakeEnvelope(45, 0, 75, 30, 4326),
        p.position_geom::geometry
      )

- Bay of Bengal:
    * Latitude between 0° and 25°N
    * Longitude between 80°E and 100°E

      WHERE
        p.latitude  BETWEEN 0  AND 25
        AND p.longitude BETWEEN 80 AND 100

    * Or, with PostGIS:

      ST_Contains(
        ST_MakeEnvelope(80, 0, 100, 25, 4326),
        p.position_geom::geometry
      )

- Near the equator / equatorial region:
    * Use absolute latitude:

      ABS(p.latitude) <= 5

QUALITY CONTROL (QC) AND SOURCES
================================

For each measured variable X (temperature, salinity, oxygen, etc.):

- X_source: 'ADJUSTED' or 'RAW'
- X_qc    : QC integer flag (1 = good).

Recommended default:
- Prefer X_source = 'ADJUSTED' AND X_qc = 1 for scientific analyses.
- If no adjusted data exist, you may fall back to including RAW or mixed QC,
  but this should be mentioned in explanations.
"""

# ---------------------------------------------------------------------------
# 2. Structured DSL view of the schema + join graph
# ---------------------------------------------------------------------------

SCHEMA_DSL = """
TABLE floats (
  float_id        VARCHAR PRIMARY KEY,
  dac             VARCHAR,
  platform_type   VARCHAR,      -- e.g. 'ARGO'
  ocean           CHAR(2)       -- basin code, e.g. 'IO' for Indian Ocean.
                                -- NOTE: this is a coarse basin label,
                                -- NOT 'Arabian Sea' or 'Bay of Bengal'.
);

TABLE profiles (
  profile_id      INTEGER PRIMARY KEY,
  float_id        VARCHAR REFERENCES floats(float_id),
  cycle_number    INTEGER,
  profile_time    TIMESTAMP,
  latitude        DOUBLE PRECISION,
  longitude       DOUBLE PRECISION,
  position_geom   GEOMETRY(Point, 4326),
  has_bgc         BOOLEAN,
  data_mode       CHAR(1)
);

TABLE measurements (
  measurement_id      INTEGER PRIMARY KEY,
  profile_id          INTEGER REFERENCES profiles(profile_id),
  pressure_dbar       DOUBLE PRECISION,
  pressure_source     VARCHAR,
  pressure_qc         INTEGER,
  depth_m             DOUBLE PRECISION,
  temperature_c       DOUBLE PRECISION,
  temperature_source  VARCHAR,
  temperature_qc      INTEGER,
  salinity_psu        DOUBLE PRECISION,
  salinity_source     VARCHAR,
  salinity_qc         INTEGER,
  doxy_umol_kg        DOUBLE PRECISION,
  doxy_source         VARCHAR,
  doxy_qc             INTEGER,
  chlorophyll_mg_m3   DOUBLE PRECISION,
  chla_source         VARCHAR,
  chla_qc             INTEGER,
  nitrate_umol_kg     DOUBLE PRECISION,
  nitrate_source      VARCHAR,
  nitrate_qc          INTEGER,
  ph_total            DOUBLE PRECISION,
  ph_source           VARCHAR,
  ph_qc               INTEGER
);

JOIN GRAPH:
  floats.float_id       = profiles.float_id
  profiles.profile_id   = measurements.profile_id
"""

JOIN_GRAPH = """
JOIN GRAPH
==========

- To combine float metadata, profile metadata, and measurements, use:

  FROM floats f
  JOIN profiles p
    ON p.float_id = f.float_id
  JOIN measurements m
    ON m.profile_id = p.profile_id

- Typically:
  * filters on time / region go on profiles (p.profile_time, p.latitude, p.longitude, p.position_geom)
  * filters on variables / QC go on measurements (m.temperature_c, m.doxy_umol_kg, etc.)
  * filters on platform type or basin go on floats (f.platform_type, f.ocean).

- Remember:
  * floats.ocean is a coarse basin code like 'IO' (Indian Ocean),
    NOT a sub-basin like 'Arabian Sea' or 'Bay of Bengal'.
  * For sub-basins, always use latitude/longitude or PostGIS on p.position_geom.
"""

# ---------------------------------------------------------------------------
# 3. Variable categories
# ---------------------------------------------------------------------------

VARIABLE_CATEGORIES = """
VARIABLE CATEGORIES
===================

CORE PHYSICAL VARIABLES
-----------------------
- temperature_c         : in situ temperature (°C)
- temperature_qc        : QC flag for temperature
- temperature_source    : 'ADJUSTED' or 'RAW'

- salinity_psu          : practical salinity (PSU)
- salinity_qc           : QC flag for salinity
- salinity_source       : 'ADJUSTED' or 'RAW'

- pressure_dbar         : pressure in dbar
- pressure_qc           : QC flag for pressure
- pressure_source       : 'ADJUSTED' or 'RAW'

- depth_m               : approximate depth (m), often similar to pressure_dbar

BGC VARIABLES
-------------
- doxy_umol_kg          : dissolved oxygen (µmol/kg)
- doxy_qc               : QC flag for oxygen
- doxy_source           : 'ADJUSTED' or 'RAW'

- chlorophyll_mg_m3     : chlorophyll-a (mg/m³)
- chla_qc               : QC flag for chlorophyll-a
- chla_source           : 'ADJUSTED' or 'RAW'

- nitrate_umol_kg       : nitrate (µmol/kg)
- nitrate_qc            : QC flag for nitrate
- nitrate_source        : 'ADJUSTED' or 'RAW'

- ph_total              : total pH
- ph_qc                 : QC flag for pH
- ph_source             : 'ADJUSTED' or 'RAW'

METADATA / INDEX COLUMNS
-------------------------
- float_id              : float/platform identifier
- cycle_number          : profile number for the float
- profile_id            : unique profile identifier
- profile_time          : timestamp of profile
- latitude, longitude   : profile position
- position_geom         : PostGIS point geometry
- has_bgc               : TRUE if BGC variables exist for the profile
- data_mode             : overall profile data mode (R/A/D etc.)

When generating visualizations:
- Use depth_m or pressure_dbar as the vertical axis for vertical profiles.
- Use profile_time as the time axis for time series.
- Use latitude and longitude for maps.
"""

# ---------------------------------------------------------------------------
# 4. Natural language synonyms + region definitions
# ---------------------------------------------------------------------------

NATURAL_LANGUAGE_SYNONYMS = """
NATURAL LANGUAGE → SCHEMA MAPPINGS AND REGION DEFINITIONS
=========================================================

GENERAL RULES
-------------
- For **regional** queries (e.g., "Arabian Sea", "Bay of Bengal", "near the equator"),
  you MUST use latitude/longitude conditions and/or PostGIS operations on profiles.position_geom.
- DO NOT filter by floats.ocean for specific seas or sub-regions.
  floats.ocean is a coarse basin code such as 'IO' for Indian Ocean.

REGIONAL SYNONYMS
-----------------

"Indian Ocean":
  - Either:
      floats.ocean = 'IO'
    OR a broad lat/lon range, such as:
      p.latitude  BETWEEN -45 AND 30
      p.longitude BETWEEN 20  AND 120

"Arabian Sea":
  - Approximate bounding box:
      p.latitude  BETWEEN 0  AND 30
      p.longitude BETWEEN 45 AND 75

  - PostGIS form:
      ST_Contains(
        ST_MakeEnvelope(45, 0, 75, 30, 4326),
        p.position_geom::geometry
      )

"Bay of Bengal":
  - Approximate bounding box:
      p.latitude  BETWEEN 0  AND 25
      p.longitude BETWEEN 80 AND 100

  - PostGIS form:
      ST_Contains(
        ST_MakeEnvelope(80, 0, 100, 25, 4326),
        p.position_geom::geometry
      )

"near the equator", "equatorial region":
  - Use absolute latitude:
      ABS(p.latitude) <= 5

"last 6 months", "past six months":
  - Prefer explicit dates when possible in examples,
    but a typical pattern is:
      p.profile_time >= NOW() - INTERVAL '6 months'

VARIABLE & COLUMN SYNONYMS
--------------------------

"temperature", "water temperature":
  → measurements.temperature_c

"salinity", "salt", "salinity profile":
  → measurements.salinity_psu

"dissolved oxygen", "oxygen", "O2":
  → measurements.doxy_umol_kg

"chlorophyll", "chlorophyll-a", "chla":
  → measurements.chlorophyll_mg_m3

"nitrate", "NO3":
  → measurements.nitrate_umol_kg

"pH", "acidity":
  → measurements.ph_total

PROFILE & TIME LANGUAGE
-----------------------

"profile", "vertical profile", "CTD profile":
  - Use measurements vs depth_m or pressure_dbar.
  - Group by profile_id (and often float_id, cycle_number).

"time series", "trend over time":
  - Use profile_time or date(profile_time) on the x-axis.
  - Aggregate or sample measurements (e.g., mean over profiles per week or month).

SPATIAL OPERATIONS
------------------

"nearest float", "closest float":
  → Use ST_DistanceSphere and order by distance:

    SELECT
      f.float_id,
      p.profile_id,
      p.profile_time,
      ST_DistanceSphere(
        p.position_geom,
        ST_SetSRID(ST_MakePoint(<lon>, <lat>), 4326)
      ) AS distance_m
    FROM floats f
    JOIN profiles p ON p.float_id = f.float_id
    ORDER BY distance_m
    LIMIT 10;

"within X km":
  → Use ST_DWithin with meters as the distance unit:

    ST_DWithin(
      p.position_geom,
      ST_SetSRID(ST_MakePoint(<lon>, <lat>), 4326),
      <X_km> * 1000
    )
"""

# ---------------------------------------------------------------------------
# 5. Example SQL patterns
# ---------------------------------------------------------------------------

EXAMPLE_SQL = """
-- Example 1: Salinity profiles near the equator in March 2023
SELECT
  p.profile_id,
  p.float_id,
  p.cycle_number,
  p.profile_time,
  p.latitude,
  p.longitude,
  m.pressure_dbar,
  m.depth_m,
  m.salinity_psu
FROM profiles p
JOIN measurements m ON m.profile_id = p.profile_id
WHERE
  p.profile_time >= '2023-03-01 00:00:00'
  AND p.profile_time <  '2023-04-01 00:00:00'
  AND ABS(p.latitude) <= 5
  AND m.salinity_psu IS NOT NULL
  AND m.salinity_source = 'ADJUSTED'
  AND m.salinity_qc = 1
ORDER BY
  p.profile_time, p.latitude, p.longitude, m.pressure_dbar;


-- Example 2: Floats operating in the Arabian Sea (using coordinates)
SELECT
  f.float_id,
  MIN(p.profile_time) AS first_profile_time,
  MAX(p.profile_time) AS last_profile_time,
  MIN(p.latitude)     AS min_lat,
  MAX(p.latitude)     AS max_lat,
  MIN(p.longitude)    AS min_lon,
  MAX(p.longitude)    AS max_lon
FROM floats f
JOIN profiles p ON p.float_id = f.float_id
WHERE
  p.latitude  BETWEEN 0  AND 30
  AND p.longitude BETWEEN 45 AND 75
GROUP BY f.float_id
ORDER BY f.float_id;


-- Example 3: Compare BGC parameters in the Arabian Sea over a fixed 6-month window
SELECT
  p.float_id,
  p.profile_time,
  p.latitude,
  p.longitude,
  m.depth_m,
  m.doxy_umol_kg,
  m.chlorophyll_mg_m3,
  m.nitrate_umol_kg,
  m.ph_total
FROM profiles p
JOIN measurements m ON m.profile_id = p.profile_id
WHERE
  p.has_bgc = TRUE
  AND p.profile_time >= '2023-06-01'
  AND p.profile_time <  '2023-12-01'
  AND p.latitude  BETWEEN 0  AND 30
  AND p.longitude BETWEEN 45 AND 75
  AND m.doxy_source        = 'ADJUSTED' AND m.doxy_qc    = 1
  AND m.chla_source        = 'ADJUSTED' AND m.chla_qc    = 1
  AND m.nitrate_source     = 'ADJUSTED' AND m.nitrate_qc = 1
  AND m.ph_source          = 'ADJUSTED' AND m.ph_qc      = 1
ORDER BY p.profile_time, m.depth_m;


-- Example 4: Bay of Bengal profiles with nitrate and chlorophyll
SELECT DISTINCT
  p.profile_id,
  p.float_id,
  p.cycle_number,
  p.profile_time,
  p.latitude,
  p.longitude
FROM profiles p
JOIN measurements m ON m.profile_id = p.profile_id
WHERE
  p.latitude  BETWEEN 5  AND 25
  AND p.longitude BETWEEN 80 AND 100
  AND p.has_bgc = TRUE
  AND m.nitrate_umol_kg      IS NOT NULL
  AND m.nitrate_source       = 'ADJUSTED'
  AND m.nitrate_qc           = 1
  AND m.chlorophyll_mg_m3    IS NOT NULL
  AND m.chla_source          = 'ADJUSTED'
  AND m.chla_qc              = 1
ORDER BY p.profile_time DESC
LIMIT 20;
"""

# ---------------------------------------------------------------------------
# 6. Plot intent spec (for front-end / viz agent)
# ---------------------------------------------------------------------------

PLOT_INTENT_SPEC = """
PLOT / VISUALIZATION INTENT SPEC
================================

The backend can infer a high-level visualization intent from the result DataFrame.
The main plot types are:

1) "profile_plot"
   - Vertical profile(s) at one or more locations.
   - Typical axes:
       x: one variable (e.g., temperature_c, salinity_psu, doxy_umol_kg)
       y: depth_m or pressure_dbar (usually plotted with depth increasing downward).
   - Grouping:
       group_by: profile_id (and optionally float_id, cycle_number)
   - Example use:
       "Show a vertical profile of oxygen and temperature near 10N, 60E in 2022."

2) "time_series"
   - Time evolution of a single variable.
   - Typical axes:
       x: profile_time (or date(profile_time))
       y: one variable (e.g., surface temperature_c, mixed-layer salinity_psu).
   - Grouping:
       group_by: float_id (or region aggregate).
   - Example use:
       "Give me a time series of dissolved oxygen in the Arabian Sea over the last 6 months."

3) "depth_time"
   - Depth-time cross-section, often shown as a 2D colored image:
       x: time (profile_time)
       y: depth_m or pressure_dbar
       color: one variable (e.g., temperature_c, chlorophyll_mg_m3).
   - Usually limited to one float or a small region.

4) "map"
   - Spatial distribution of profiles or variables.
   - Typical axes:
       x: longitude
       y: latitude
       color/size: optional scalar like surface temperature_c or chlorophyll_mg_m3.
   - Example use:
       "Map the last 100 profiles with BGC data in the Arabian Sea."

5) "table"
   - Fallback when no strong plot structure is detected.
   - The data are shown as a tabular result without plotting.

The visualization intent object typically includes:
  {
    "kind": "map" | "profile_plot" | "time_series" | "depth_time" | "table",
    "variables": [...],     -- numeric data variables
    "group_by": [...],      -- grouping keys (e.g., profile_id, float_id)
    "x": "...",             -- suggested x-axis column
    "y": "...",             -- suggested y-axis column
    "variable": "..."       -- primary scalar variable for color/value
  }
"""

# ---------------------------------------------------------------------------
# 7. SQL repair tips
# ---------------------------------------------------------------------------

QUERY_REPAIR_TIPS = """
SQL REPAIR TIPS
===============

Typical error patterns and how to fix them:

1) Geometry vs geography mismatch
---------------------------------
Error like:
  function st_contains(geometry, geography) does not exist

Fix:
  - Ensure both arguments to ST_Contains (and related functions) are GEOMETRY.
  - Cast position_geom to geometry explicitly:

    ST_Contains(
      ST_MakeEnvelope(45, 0, 75, 30, 4326),
      p.position_geom::geometry
    )

2) Using floats.ocean for sub-regions
-------------------------------------
Wrong:
  WHERE f.ocean = 'ARABIAN SEA'

Fix:
  - Use latitude/longitude or envelopes on profiles:

    WHERE
      p.latitude  BETWEEN 0  AND 30
      AND p.longitude BETWEEN 45 AND 75

  or the corresponding ST_MakeEnvelope pattern.

3) Missing GROUP BY with aggregates
-----------------------------------
Error:
  column "p.float_id" must appear in the GROUP BY clause or be used in an aggregate function

Fix:
  - When using aggregate functions (MIN, MAX, AVG, COUNT, etc.), every selected
    non-aggregated column must appear in GROUP BY:

    SELECT
      f.float_id,
      MIN(p.profile_time) AS first_time
    FROM ...
    GROUP BY f.float_id;

4) Ambiguous column references
------------------------------
If both profiles and measurements have columns with similar names (e.g., profile_id),
you should always qualify them with table aliases:

  p.profile_id, m.pressure_dbar, f.float_id

5) LIMIT and performance
------------------------
- For exploratory or plotting queries, always use a LIMIT at the end
  (e.g., LIMIT 500 or LIMIT 2000) to keep responses fast.
- The backend may automatically clamp LIMIT to a safe maximum.

When repairing SQL:
- Preserve the original scientific intent (region, variables, QC rules).
- Only change the minimal necessary pieces: joins, aliases, GROUP BY, casts, etc.
"""

# ---------------------------------------------------------------------------
# 8. MCP / tools description
# ---------------------------------------------------------------------------

MCP_TOOLS_TEXT = """
MCP TOOLS (BACKEND CAPABILITIES)
================================

The system exposes several backend tools in a Model Context Protocol (MCP) style.
Key tools include:

1) tool_run_sql(sql: str) → DataFrame
   - Executes a validated, read-only SQL query (SELECT/WITH only) against the
     Indian Ocean ARGO + BGC database.
   - Returns a tabular result (DataFrame) with columns exactly as selected.

   Constraints enforced by the backend:
   - No INSERT/UPDATE/DELETE/DDL.
   - LIMIT is automatically added or clamped.
   - SQL is checked by sql_guard.ensure_safe_sql before execution.

2) tool_describe_dataframe(df) → JSON string
   - Produces a compact JSON summary of a result DataFrame, including:
     * column names and types
     * number of rows
     * basic statistics for numeric columns (min, max, mean)
     * time range for any datetime columns (e.g., profile_time)
   - This summary is used by the AI to provide a narrative explanation of the data.

Higher-level logic:
- The NL→SQL agent generates a candidate SQL via tool_run_sql.
- If the query fails, a repair step is attempted using the DB error message.
- Once a valid DataFrame is returned, tool_describe_dataframe(df) is called and
  the AI produces a human-readable interpretation for decision-makers.
"""

