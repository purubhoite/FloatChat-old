# backend/date_rewriter.py

"""
Date rewriter for FloatChat queries.

Converts relative date expressions like "last 6 months", "past year" 
into explicit date bounds that can be used in SQL queries.
"""

import re
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from typing import Tuple, Optional


def get_current_date() -> datetime:
    """Get the current date. Using datetime.now() for real-time behavior."""
    return datetime.now()


def parse_relative_date(query: str, reference_date: Optional[datetime] = None) -> Tuple[Optional[str], Optional[str]]:
    """
    Parse relative date expressions from a query and return explicit date bounds.
    
    Args:
        query: User's natural language query
        reference_date: Reference date (defaults to current date)
        
    Returns:
        Tuple of (start_date, end_date) as ISO format strings 'YYYY-MM-DD',
        or (None, None) if no relative date expression is found.
        
    Examples:
        >>> parse_relative_date("data from last 6 months")
        ('2025-06-09', '2025-12-09')
        >>> parse_relative_date("profiles in past year")
        ('2024-12-09', '2025-12-09')
    """
    if reference_date is None:
        reference_date = get_current_date()
    
    query_lower = query.lower()
    
    # Pattern: "last N months" or "past N months"
    match = re.search(r'\b(last|past)\s+(\d+)\s+months?\b', query_lower)
    if match:
        num_months = int(match.group(2))
        start_date = reference_date - relativedelta(months=num_months)
        return (start_date.strftime('%Y-%m-%d'), reference_date.strftime('%Y-%m-%d'))
    
    # Pattern: "last N days" or "past N days"
    match = re.search(r'\b(last|past)\s+(\d+)\s+days?\b', query_lower)
    if match:
        num_days = int(match.group(2))
        start_date = reference_date - timedelta(days=num_days)
        return (start_date.strftime('%Y-%m-%d'), reference_date.strftime('%Y-%m-%d'))
    
    # Pattern: "last N weeks" or "past N weeks"
    match = re.search(r'\b(last|past)\s+(\d+)\s+weeks?\b', query_lower)
    if match:
        num_weeks = int(match.group(2))
        start_date = reference_date - timedelta(weeks=num_weeks)
        return (start_date.strftime('%Y-%m-%d'), reference_date.strftime('%Y-%m-%d'))
    
    # Pattern: "last N years" or "past N years"
    match = re.search(r'\b(last|past)\s+(\d+)\s+years?\b', query_lower)
    if match:
        num_years = int(match.group(2))
        start_date = reference_date - relativedelta(years=num_years)
        return (start_date.strftime('%Y-%m-%d'), reference_date.strftime('%Y-%m-%d'))
    
    # Pattern: "last year" or "past year" (without number)
    if re.search(r'\b(last|past)\s+year\b', query_lower):
        start_date = reference_date - relativedelta(years=1)
        return (start_date.strftime('%Y-%m-%d'), reference_date.strftime('%Y-%m-%d'))
    
    # Pattern: "last month" or "past month" (without number)
    if re.search(r'\b(last|past)\s+month\b', query_lower):
        start_date = reference_date - relativedelta(months=1)
        return (start_date.strftime('%Y-%m-%d'), reference_date.strftime('%Y-%m-%d'))
    
    # Pattern: "last week" or "past week" (without number)
    if re.search(r'\b(last|past)\s+week\b', query_lower):
        start_date = reference_date - timedelta(weeks=1)
        return (start_date.strftime('%Y-%m-%d'), reference_date.strftime('%Y-%m-%d'))
    
    # Pattern: "since YYYY" or "from YYYY"
    match = re.search(r'\b(since|from)\s+(20\d{2})\b', query_lower)
    if match:
        year = int(match.group(2))
        start_date = datetime(year, 1, 1)
        return (start_date.strftime('%Y-%m-%d'), reference_date.strftime('%Y-%m-%d'))
    
    # Pattern: "in YYYY" (specific year)
    match = re.search(r'\bin\s+(20\d{2})\b', query_lower)
    if match:
        year = int(match.group(1))
        start_date = datetime(year, 1, 1)
        end_date = datetime(year, 12, 31)
        # If the year is current year, use reference_date as end
        if year == reference_date.year:
            end_date = reference_date
        return (start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
    
    # Pattern: "recent" (default to last 3 months)
    if re.search(r'\brecent\b', query_lower):
        start_date = reference_date - relativedelta(months=3)
        return (start_date.strftime('%Y-%m-%d'), reference_date.strftime('%Y-%m-%d'))
    
    # No relative date found
    return (None, None)


def rewrite_query_with_dates(query: str, reference_date: Optional[datetime] = None) -> str:
    """
    Rewrite a query to include explicit date bounds if relative dates are detected.
    
    Args:
        query: Original user query
        reference_date: Reference date (defaults to current date)
        
    Returns:
        Query with appended date context, or original query if no relative dates found.
        
    Examples:
        >>> rewrite_query_with_dates("data from last 6 months")
        "data from last 6 months [Date range: 2025-06-09 to 2025-12-09]"
    """
    start_date, end_date = parse_relative_date(query, reference_date)
    
    if start_date and end_date:
        return f"{query} [Date range: {start_date} to {end_date}]"
    
    return query


def get_date_context_for_prompt(reference_date: Optional[datetime] = None) -> str:
    """
    Generate a date context string to include in LLM prompts.
    
    Args:
        reference_date: Reference date (defaults to current date)
        
    Returns:
        String with current date information for LLM context.
    """
    if reference_date is None:
        reference_date = get_current_date()
    
    return f"""
CURRENT DATE CONTEXT:
Today's date is {reference_date.strftime('%Y-%m-%d')} ({reference_date.strftime('%B %d, %Y')}).

When the user mentions relative time periods, calculate the explicit date bounds:
- "last 2 months" means from {(reference_date - relativedelta(months=2)).strftime('%Y-%m-%d')} to {reference_date.strftime('%Y-%m-%d')}
- "last 6 months" means from {(reference_date - relativedelta(months=6)).strftime('%Y-%m-%d')} to {reference_date.strftime('%Y-%m-%d')}
- "past year" means from {(reference_date - relativedelta(years=1)).strftime('%Y-%m-%d')} to {reference_date.strftime('%Y-%m-%d')}
- "recent" means approximately the last 3 months

ALWAYS use these calculated date bounds in your SQL queries. Never use hardcoded dates from 2024 or earlier.
"""


# Quick tests
if __name__ == "__main__":
    test_date = datetime(2025, 12, 9)  # Fixed test date
    
    test_cases = [
        "compare bgc parameters in arabian sea in last 2 months",
        "show temperature profiles from last 6 months",
        "oxygen data from past year",
        "salinity trends since 2024",
        "profiles in 2025",
        "recent chlorophyll data",
        "data from last 30 days",
        "floats from past 2 weeks",
    ]
    
    print("Testing date parser...")
    print(f"Reference date: {test_date.strftime('%Y-%m-%d')}\n")
    
    for query in test_cases:
        start, end = parse_relative_date(query, test_date)
        print(f"Query: '{query}'")
        print(f"  -> Date range: {start} to {end}\n")
