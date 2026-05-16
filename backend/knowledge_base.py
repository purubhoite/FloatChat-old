# backend/knowledge_base.py

"""
Knowledge base for FloatChat containing domain knowledge about ARGO, BGC, and oceanographic concepts.

This module provides predefined answers for definition/knowledge queries,
avoiding unnecessary SQL generation for conceptual questions.
"""

from typing import Optional, Dict, Any, List
import json

from .llm import call_llm_json


# ============================================================================
# ARGO & BGC DOMAIN KNOWLEDGE
# ============================================================================

KNOWLEDGE_BASE: Dict[str, Dict[str, str]] = {
    # -------------------------------------------------------------------------
    # ARGO PROGRAM
    # -------------------------------------------------------------------------
    "argo": {
        "title": "ARGO Program",
        "content": """
ARGO is an international program that uses a global array of autonomous profiling floats to observe the ocean. 
Key facts:
- **Started**: 2000, now with ~4000 active floats worldwide
- **Purpose**: Monitor ocean temperature, salinity, and currents in real-time
- **Coverage**: All major ocean basins from 60°S to 60°N
- **Depth**: Measures from surface to 2000m (some Deep ARGO floats go to 6000m)
- **Data**: Freely available within 24 hours of collection
- **Partners**: 30+ countries contribute floats and data

ARGO provides essential data for climate research, weather forecasting, and ocean monitoring.
"""
    },
    
    "float": {
        "title": "ARGO Float",
        "content": """
An ARGO float is an autonomous underwater profiling instrument.

**How it works:**
1. **Parking depth**: Float drifts at ~1000m depth between profiles
2. **Descent**: Sinks to profile start depth (typically 2000m)
3. **Ascent**: Rises while measuring temperature, salinity, pressure
4. **Surface**: Transmits data via satellite, then descends again
5. **Cycle time**: Typically 10 days per profile cycle

**Components:**
- Pressure case (aluminum or glass)
- CTD sensor (Conductivity-Temperature-Depth)
- Satellite antenna (Iridium or ARGOS)
- Battery (lithium, 3-5 year lifespan)
- Buoyancy engine (oil bladder)

Each float is identified by a unique **WMO ID** (7-digit number).
"""
    },
    
    "profile": {
        "title": "Ocean Profile",
        "content": """
A profile is a single vertical measurement from an ARGO float - one complete ascent cycle.

**What's measured:**
- **Depth levels**: Typically 50-100+ measurement points per profile
- **Variables**: Temperature, salinity, pressure (and BGC parameters if equipped)
- **Location**: GPS position when surfaced

**Profile metadata:**
- `profile_id`: Unique identifier
- `float_id`: Which float took the measurement  
- `cycle_number`: Sequential number for that float
- `profile_time`: UTC timestamp
- `latitude/longitude`: Surface position

**Example**: Float 2902086, cycle 42, at 15.2°N, 68.5°E on 2023-03-15
"""
    },
    
    "difference_float_profile": {
        "title": "Float vs Profile",
        "content": """
**Float** and **Profile** are related but different:

| Aspect | Float | Profile |
|--------|-------|---------|
| **What** | Physical instrument | Single measurement cycle |
| **Count** | 1 float = many profiles | 1 profile = 1 vertical measurement |
| **Lifespan** | 3-5 years | ~10 days between profiles |
| **ID** | WMO ID (e.g., "2902086") | profile_id (integer) |

**Relationship**: One float produces hundreds of profiles over its lifetime.

Example: Float 2902086 might have 150 profiles over 4 years, each measuring the water column at a different time and location.
"""
    },
    
    # -------------------------------------------------------------------------
    # BGC PARAMETERS
    # -------------------------------------------------------------------------
    "bgc": {
        "title": "Biogeochemical (BGC) Parameters",
        "content": """
BGC-ARGO floats carry additional sensors beyond standard temperature/salinity:

| Parameter | Column | Units | Measures |
|-----------|--------|-------|----------|
| **Dissolved Oxygen** | `doxy_umol_kg` | µmol/kg | Ocean respiration, productivity |
| **Chlorophyll-a** | `chlorophyll_mg_m3` | mg/m³ | Phytoplankton biomass |
| **Nitrate** | `nitrate_umol_kg` | µmol/kg | Ocean nutrients |
| **pH** | `ph_total` | - | Ocean acidification |

**Why BGC matters:**
- Monitors ocean health and carbon cycle
- Tracks biological productivity
- Detects oxygen minimum zones
- Studies climate change effects

**Database**: Use `p.has_bgc = TRUE` to filter for BGC-equipped profiles.
"""
    },
    
    "oxygen": {
        "title": "Dissolved Oxygen (DOXY)",
        "content": """
Dissolved oxygen measures the amount of O₂ gas dissolved in seawater.

**Column**: `doxy_umol_kg` (units: µmol/kg)

**Why it matters:**
- Indicates ocean ventilation and circulation
- Essential for marine life
- Helps identify oxygen minimum zones (OMZ)

**Typical values:**
- Surface: 200-300 µmol/kg (near saturation)
- Deep ocean: 100-200 µmol/kg
- OMZ: <50 µmol/kg

**Quality flags**: Use `doxy_source = 'ADJUSTED'` and `doxy_qc = 1` for reliable data.
"""
    },
    
    "chlorophyll": {
        "title": "Chlorophyll-a",
        "content": """
Chlorophyll-a is the primary photosynthetic pigment in phytoplankton.

**Column**: `chlorophyll_mg_m3` (units: mg/m³)

**Why it matters:**
- Proxy for phytoplankton biomass
- Indicates ocean biological productivity
- Important for carbon cycle studies

**Typical values:**
- Open ocean: 0.1-0.5 mg/m³
- Coastal/upwelling: 1-10+ mg/m³
- Deep chlorophyll maximum: Usually at 50-100m depth

**Quality flags**: Use `chla_source = 'ADJUSTED'` and `chla_qc = 1` for reliable data.
"""
    },
    
    "nitrate": {
        "title": "Nitrate",
        "content": """
Nitrate (NO₃⁻) is a key nutrient for phytoplankton growth.

**Column**: `nitrate_umol_kg` (units: µmol/kg)

**Why it matters:**
- Essential nutrient limiting primary production
- Indicator of nutrient supply and upwelling
- Used to study nitrogen cycle

**Typical values:**
- Surface (tropical): ~0 µmol/kg (depleted)
- Surface (polar): 5-20 µmol/kg
- Deep ocean: 20-40 µmol/kg

**Quality flags**: Use `nitrate_source = 'ADJUSTED'` and `nitrate_qc = 1` for reliable data.
"""
    },
    
    "ph": {
        "title": "Ocean pH",
        "content": """
pH measures ocean acidity/alkalinity on the total scale.

**Column**: `ph_total` (dimensionless)

**Why it matters:**
- Tracks ocean acidification
- Affects marine organism calcification
- Important for carbon cycle studies

**Typical values:**
- Surface ocean: 8.0-8.2
- Deep ocean: 7.6-7.9
- Decreasing ~0.02 units per decade due to CO₂ uptake

**Quality flags**: Use `ph_source = 'ADJUSTED'` and `ph_qc = 1` for reliable data.
"""
    },
    
    # -------------------------------------------------------------------------
    # DATA QUALITY
    # -------------------------------------------------------------------------
    "qc": {
        "title": "Quality Control (QC) Flags",
        "content": """
ARGO uses Quality Control flags to indicate data reliability.

**QC Flag values:**
| Flag | Meaning |
|------|---------|
| 0 | No QC performed |
| 1 | **Good data** ✓ (recommended) |
| 2 | Probably good |
| 3 | Probably bad |
| 4 | Bad data ✗ |
| 5 | Value changed |
| 8 | Interpolated |
| 9 | Missing |

**Best practice**: Filter for `*_qc = 1` for trusted data.

Each variable has its own QC column:
- `temperature_qc`, `salinity_qc`
- `doxy_qc`, `chla_qc`, `nitrate_qc`, `ph_qc`
"""
    },
    
    "adjusted_vs_raw": {
        "title": "Adjusted vs Raw Data",
        "content": """
ARGO provides both raw and adjusted (calibrated) data:

| Type | Source Column | Description |
|------|---------------|-------------|
| **RAW** | `*_source = 'RAW'` | Direct sensor reading, uncorrected |
| **ADJUSTED** | `*_source = 'ADJUSTED'` | Calibrated, scientifically validated |

**Why adjusted data is better:**
- Sensor drift corrections applied
- Delayed-mode quality control performed
- Calibrated against reference data

**Recommendation**: Always use `*_source = 'ADJUSTED'` when available.
"""
    },
    
    "data_mode": {
        "title": "Data Mode",
        "content": """
Data mode indicates the processing level of ARGO data:

| Mode | Description | Delay |
|------|-------------|-------|
| **R** (Real-time) | Automatic QC only | < 24 hours |
| **A** (Adjusted) | Some adjustments applied | Days to weeks |
| **D** (Delayed) | Full scientific QC | 6-12 months |

**Column**: `data_mode` in profiles table

**Recommendation**: For research, prefer `data_mode = 'D'` for most reliable data.
"""
    },
    
    # -------------------------------------------------------------------------
    # REGIONS
    # -------------------------------------------------------------------------
    "arabian_sea": {
        "title": "Arabian Sea",
        "content": """
The Arabian Sea is the northwestern part of the Indian Ocean.

**Boundaries:**
- Latitude: 0°N to 30°N
- Longitude: 45°E to 75°E

**SQL filter:**
```sql
p.latitude BETWEEN 0 AND 30
AND p.longitude BETWEEN 45 AND 75
```

**Oceanographic features:**
- Strong seasonal monsoon circulation
- Major upwelling zones (especially off Oman/Somalia)
- Seasonal oxygen minimum zone (OMZ)
- High biological productivity
"""
    },
    
    "bay_of_bengal": {
        "title": "Bay of Bengal",
        "content": """
The Bay of Bengal is the northeastern part of the Indian Ocean.

**Boundaries:**
- Latitude: 0°N to 25°N  
- Longitude: 80°E to 100°E

**SQL filter:**
```sql
p.latitude BETWEEN 0 AND 25
AND p.longitude BETWEEN 80 AND 100
```

**Oceanographic features:**
- High freshwater input from rivers (Ganges, Brahmaputra)
- Strong stratification, low surface salinity
- Cyclone-prone region
- Less biological productivity than Arabian Sea
"""
    },
    
    "indian_ocean": {
        "title": "Indian Ocean",
        "content": """
The Indian Ocean is the third-largest ocean, bounded by Africa, Asia, and Australia.

**Approximate boundaries:**
- Latitude: -45°S to 30°N
- Longitude: 20°E to 120°E

**SQL filter:**
```sql
f.ocean = 'IO'
-- OR --
p.latitude BETWEEN -45 AND 30
AND p.longitude BETWEEN 20 AND 120
```

**Key regions:**
- Arabian Sea (northwest)
- Bay of Bengal (northeast)
- Equatorial Indian Ocean
- Southern Indian Ocean

**Unique features:**
- Monsoon-driven circulation (reverses seasonally)
- Indonesian Throughflow connection to Pacific
"""
    },
    
    # -------------------------------------------------------------------------
    # DATABASE SCHEMA
    # -------------------------------------------------------------------------
    "database_tables": {
        "title": "Database Tables",
        "content": """
The FloatChat database has three main tables:

**1. floats** - Float metadata
- `float_id`: Unique WMO identifier
- `dac`: Data Assembly Center
- `platform_type`: Usually 'ARGO'
- `ocean`: Basin code ('IO' for Indian Ocean)

**2. profiles** - Profile metadata
- `profile_id`: Unique profile ID
- `float_id`: Which float (FK)
- `cycle_number`: Sequence number
- `profile_time`: Timestamp
- `latitude`, `longitude`: Position
- `has_bgc`: Has BGC sensors

**3. measurements** - Depth-level data
- `measurement_id`: Unique ID
- `profile_id`: Which profile (FK)
- `depth_m`, `pressure_dbar`: Vertical coordinate
- `temperature_c`, `salinity_psu`: Core vars
- BGC: `doxy_umol_kg`, `chlorophyll_mg_m3`, `nitrate_umol_kg`, `ph_total`
"""
    },
    
    # -------------------------------------------------------------------------
    # APPLICATION
    # -------------------------------------------------------------------------
    "how_to_use": {
        "title": "How to Use FloatChat",
        "content": """
FloatChat lets you explore Indian Ocean ARGO data using natural language.

**Types of queries you can ask:**

1. **Data queries** (generates SQL):
   - "Show temperature profiles in Arabian Sea"
   - "Plot dissolved oxygen vs depth"
   - "List floats with BGC data"
   
2. **Knowledge queries** (answered directly):
   - "What is ARGO?"
   - "Difference between float and profile"
   - "What are BGC parameters?"

**Tips:**
- Be specific about regions, time periods, and variables
- Use follow-up questions ("What about temperature?")
- Check the SQL panel to see what query was run
- Download data as CSV for further analysis
"""
    },
}


# ============================================================================
# QUERY MATCHING
# ============================================================================

# Map of keywords/phrases to knowledge base keys
KEYWORD_MAPPING = {
    # ARGO
    "argo": "argo",
    "argo program": "argo",
    
    # Float
    "float": "float",
    "floats": "float",
    "argo float": "float",
    "profiling float": "float",
    
    # Profile
    "profile": "profile",
    "profiles": "profile",
    "vertical profile": "profile",
    "ocean profile": "profile",
    
    # Float vs Profile
    "difference between float and profile": "difference_float_profile",
    "float vs profile": "difference_float_profile",
    "float versus profile": "difference_float_profile",
    "profile vs float": "difference_float_profile",
    
    # BGC
    "bgc": "bgc",
    "biogeochemical": "bgc",
    "bgc parameters": "bgc",
    "bgc variables": "bgc",
    "biogeochemical parameters": "bgc",
    
    # Individual BGC parameters
    "oxygen": "oxygen",
    "dissolved oxygen": "oxygen",
    "doxy": "oxygen",
    "o2": "oxygen",
    
    "chlorophyll": "chlorophyll",
    "chlorophyll-a": "chlorophyll",
    "chla": "chlorophyll",
    "chl-a": "chlorophyll",
    
    "nitrate": "nitrate",
    "no3": "nitrate",
    
    "ph": "ph",
    "acidity": "ph",
    "ocean ph": "ph",
    
    # Data quality
    "qc": "qc",
    "quality control": "qc",
    "qc flag": "qc",
    "qc flags": "qc",
    "quality flag": "qc",
    
    "adjusted": "adjusted_vs_raw",
    "raw data": "adjusted_vs_raw",
    "adjusted data": "adjusted_vs_raw",
    "adjusted vs raw": "adjusted_vs_raw",
    
    "data mode": "data_mode",
    "real-time": "data_mode",
    "delayed mode": "data_mode",
    
    # Regions
    "arabian sea": "arabian_sea",
    "arabian": "arabian_sea",
    
    "bay of bengal": "bay_of_bengal",
    "bengal": "bay_of_bengal",
    
    "indian ocean": "indian_ocean",
    
    # Database
    "database": "database_tables",
    "tables": "database_tables",
    "schema": "database_tables",
    
    # App usage
    "how to use": "how_to_use",
    "help": "how_to_use",
    "how does this work": "how_to_use",
}


def _find_matching_topics(query: str) -> List[str]:
    """Find all knowledge base topics that match the query."""
    query_lower = query.lower()
    matches = []
    
    # Check each keyword mapping
    for keyword, topic_key in KEYWORD_MAPPING.items():
        if keyword in query_lower:
            if topic_key not in matches:
                matches.append(topic_key)
    
    return matches


def get_knowledge_answer(
    query: str, 
    conversation_history: Optional[List[Dict[str, str]]] = None
) -> str:
    """
    Generate an answer for a knowledge/definition query.
    
    Args:
        query: The user's question
        conversation_history: Optional previous messages for context
        
    Returns:
        A natural language answer about the requested topic
    """
    query_lower = query.lower().strip()
    
    # Find matching topics
    matching_topics = _find_matching_topics(query_lower)
    
    if not matching_topics:
        # No direct match - use LLM with general ARGO context
        return _generate_llm_answer(query, conversation_history)
    
    # Build context from matching knowledge base entries
    knowledge_context = ""
    for topic_key in matching_topics[:3]:  # Limit to top 3 matches
        if topic_key in KNOWLEDGE_BASE:
            entry = KNOWLEDGE_BASE[topic_key]
            knowledge_context += f"\n## {entry['title']}\n{entry['content']}\n"
    
    # Use LLM to generate a natural answer using the knowledge context
    return _generate_llm_answer(query, conversation_history, knowledge_context)


def _generate_llm_answer(
    query: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    knowledge_context: str = ""
) -> str:
    """Generate a natural language answer using the LLM."""
    
    # Build conversation context
    conv_context = ""
    if conversation_history:
        conv_context = "\n\nPrevious conversation:\n"
        for msg in conversation_history[-4:]:
            role = "User" if msg.get("role") == "user" else "Assistant"
            text = msg.get("text", "")
            conv_context += f"{role}: {text}\n"
    
    # If no specific knowledge found, use general context
    if not knowledge_context:
        knowledge_context = """
You are an expert on the ARGO oceanographic observation program and its data.
ARGO uses autonomous profiling floats to measure ocean temperature, salinity, and 
biogeochemical parameters like dissolved oxygen, chlorophyll, nitrate, and pH.
The Indian Ocean database contains data from floats, profiles, and measurements tables.
"""
    
    prompt = f"""You are FloatChat, an assistant for the Indian Ocean ARGO data explorer.
Answer the user's question based on the following knowledge:

{knowledge_context}
{conv_context}

User question: {query}

Provide a clear, helpful, and accurate answer. Be concise but informative.
If you don't have specific information, say so honestly.

Return your answer as JSON: {{"explanation": "Your answer here"}}
"""

    try:
        json_text = call_llm_json(prompt)
        parsed = json.loads(json_text)
        return parsed.get("explanation", "I don't have specific information about that topic.")
    except Exception as e:
        # Fallback: return the raw knowledge content if available
        if knowledge_context and "##" in knowledge_context:
            return knowledge_context.strip()
        return "I apologize, but I couldn't generate an answer for that question. Please try rephrasing."


# Quick test
if __name__ == "__main__":
    test_queries = [
        "What is ARGO?",
        "What is a float?",
        "Difference between float and profile",
        "What are BGC parameters?",
        "Explain dissolved oxygen",
        "What does QC mean?",
        "Tell me about the Arabian Sea",
    ]
    
    print("Testing knowledge base...\n")
    for q in test_queries:
        topics = _find_matching_topics(q)
        print(f"Query: '{q}'")
        print(f"  → Matched topics: {topics}")
        print()
