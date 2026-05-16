# backend/intent_classifier.py

"""
Intent classifier for FloatChat queries.

Classifies user queries into:
- "knowledge": Definition/explanation queries (no SQL needed)
- "data_query": Data retrieval queries (needs SQL)

Uses keyword-based detection for fast classification.
"""

import re
from typing import Literal, List

QueryIntent = Literal["knowledge", "data_query"]


# Knowledge query indicators - questions about concepts, definitions, explanations
KNOWLEDGE_PATTERNS = [
    # Direct definition questions
    r"\bwhat\s+is\s+(an?\s+)?",
    r"\bwhat\s+are\s+",
    r"\bdefine\s+",
    r"\bdefinition\s+of\s+",
    r"\bexplain\s+(what\s+)?",
    r"\bdescribe\s+(what\s+)?",
    r"\btell\s+me\s+about\s+",
    r"\bwhat\s+does\s+.+\s+mean",
    r"\bmeaning\s+of\s+",
    
    # Comparison/difference questions
    r"\bdifference\s+between\s+",
    r"\bcompare\s+.+\s+(and|vs|versus)\s+",
    r"\bhow\s+.+\s+differ",
    r"\bwhat('s|\s+is)\s+the\s+difference\s+",
    
    # How it works questions
    r"\bhow\s+does\s+.+\s+work",
    r"\bhow\s+do\s+.+\s+work",
    r"\bhow\s+is\s+.+\s+(measured|calculated|collected)",
    
    # Why questions about concepts
    r"\bwhy\s+(is|are|do|does)\s+",
    
    # General knowledge
    r"\bwhat\s+.*\s+used\s+for",
    r"\bpurpose\s+of\s+",
    r"\bwhat\s+.*\s+stands?\s+for",  # acronym questions
]

# Domain terms that indicate knowledge queries when combined with patterns above
DOMAIN_TERMS = [
    "argo", "float", "floats", "profile", "profiles", "bgc", "biogeochemical",
    "oxygen", "doxy", "chlorophyll", "chla", "nitrate", "ph", "salinity",
    "temperature", "pressure", "depth", "qc", "quality control", "adjusted",
    "raw", "data mode", "cycle", "descent", "ascent", "parking depth",
    "indian ocean", "arabian sea", "bay of bengal", "equator",
    "sensor", "dac", "gdac", "platform", "wmo"
]

# Data query indicators - clear signals that user wants actual data
DATA_QUERY_PATTERNS = [
    # Show/display data
    r"\bshow\s+(me\s+)?",
    r"\bdisplay\s+",
    r"\blist\s+(all\s+)?",
    r"\bget\s+(me\s+)?",
    r"\bfind\s+",
    r"\bretrieve\s+",
    r"\bfetch\s+",
    
    # Plot/visualize
    r"\bplot\s+",
    r"\bgraph\s+",
    r"\bvisualize\s+",
    r"\bdraw\s+",
    r"\bmap\s+of\s+",
    
    # Specific data requests
    r"\bprofiles?\s+(in|from|near|for|of)\s+",
    r"\bdata\s+(in|from|for)\s+",
    r"\bmeasurements?\s+(in|from|for)\s+",
    r"\bvalues?\s+(in|from|for)\s+",
    
    # Time-based requests
    r"\bin\s+(january|february|march|april|may|june|july|august|september|october|november|december)",
    r"\bin\s+20\d{2}",
    r"\bsince\s+20\d{2}",
    r"\bbetween\s+",
    r"\blast\s+\d+\s+(days?|weeks?|months?|years?)",
    r"\brecent\s+",
    
    # Location-based requests (with data context)
    r"\b(in|near|from)\s+(the\s+)?(arabian|bengal|indian|equator)",
    
    # Comparison of data
    r"\bcompare\s+.+\s+data",
    r"\btrend",
    r"\btime\s+series",
    r"\bvertical\s+profile",
    
    # Filter/where
    r"\bwhere\s+",
    r"\bfilter\s+",
    r"\bonly\s+",
    
    # Aggregation
    r"\baverage\s+",
    r"\bmean\s+",
    r"\bmax(imum)?\s+",
    r"\bmin(imum)?\s+",
    r"\bcount\s+",
]


def _has_pattern_match(text: str, patterns: List[str]) -> bool:
    """Check if text matches any of the given regex patterns."""
    text_lower = text.lower()
    for pattern in patterns:
        if re.search(pattern, text_lower):
            return True
    return False


def _has_domain_term(text: str) -> bool:
    """Check if text contains any domain-specific terms."""
    text_lower = text.lower()
    for term in DOMAIN_TERMS:
        if term in text_lower:
            return True
    return False


def classify_query_intent(query: str) -> QueryIntent:
    """
    Classify the intent of a user query.
    
    Args:
        query: The user's natural language query
        
    Returns:
        "knowledge" for definition/explanation queries
        "data_query" for data retrieval queries
    
    Examples:
        >>> classify_query_intent("What is ARGO?")
        "knowledge"
        >>> classify_query_intent("Show temperature profiles in Arabian Sea")
        "data_query"
        >>> classify_query_intent("Difference between float and profile")
        "knowledge"
    """
    query_lower = query.lower().strip()
    
    # Empty query
    if not query_lower:
        return "data_query"
    
    # PRIORITY CHECK: "difference between" is ALWAYS a knowledge query
    # This must be checked before data patterns since "between" is also a data pattern
    if re.search(r"\bdifference\s+between\b", query_lower):
        return "knowledge"
    
    # Check for strong data query indicators first
    # These almost always mean the user wants actual data
    has_data_pattern = _has_pattern_match(query_lower, DATA_QUERY_PATTERNS)
    has_knowledge_pattern = _has_pattern_match(query_lower, KNOWLEDGE_PATTERNS)
    
    # Strong data query signals
    if has_data_pattern and not has_knowledge_pattern:
        return "data_query"
    
    # Strong knowledge query signals
    if has_knowledge_pattern and not has_data_pattern:
        return "knowledge"
    
    # Both patterns present - need to disambiguate
    if has_knowledge_pattern and has_data_pattern:
        # If it starts with "what is" or similar, likely knowledge
        if re.match(r"^(what|define|explain|describe|tell\s+me|difference)\s+", query_lower):
            return "knowledge"
        # Otherwise treat as data query
        return "data_query"
    
    # No clear patterns - check for domain terms
    # Short queries with domain terms might be knowledge questions
    if len(query_lower.split()) <= 5 and _has_domain_term(query_lower):
        # Very short queries like "ARGO" or "What's BGC" are likely knowledge
        if len(query_lower.split()) <= 3:
            return "knowledge"
    
    # Default to data query (the main use case of the app)
    return "data_query"


# Quick tests
if __name__ == "__main__":
    test_cases = [
        # Knowledge queries
        ("What is ARGO?", "knowledge"),
        ("What is a float?", "knowledge"),
        ("What are BGC parameters?", "knowledge"),
        ("Difference between float and profile", "knowledge"),
        ("Explain dissolved oxygen", "knowledge"),
        ("How does an ARGO float work?", "knowledge"),
        ("What does QC mean?", "knowledge"),
        ("Define salinity", "knowledge"),
        ("Tell me about chlorophyll", "knowledge"),
        
        # Data queries
        ("Show temperature profiles in Arabian Sea", "data_query"),
        ("Plot salinity vs depth", "data_query"),
        ("List floats with BGC data", "data_query"),
        ("Get oxygen profiles from March 2023", "data_query"),
        ("Temperature trends in Bay of Bengal", "data_query"),
        ("Map of floats near the equator", "data_query"),
        ("Average salinity in 2023", "data_query"),
        ("Show me profiles from float 123", "data_query"),
    ]
    
    print("Testing intent classifier...\n")
    passed = 0
    for query, expected in test_cases:
        result = classify_query_intent(query)
        status = "PASS" if result == expected else "FAIL"
        if result == expected:
            passed += 1
        print(f"{status}: '{query}' -> {result} (expected: {expected})")
    
    print(f"\n{passed}/{len(test_cases)} tests passed")
