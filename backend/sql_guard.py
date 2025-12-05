# backend/sql_guard.py

import re
import pandas as pd
from sqlalchemy import text

from .db import engine

# Disallow any write / DDL / privilege operations
FORBIDDEN_KEYWORDS = [
    "INSERT", "UPDATE", "DELETE", "DROP", "TRUNCATE",
    "ALTER", "CREATE", "GRANT", "REVOKE", "COMMENT",
]


class SqlValidationError(Exception):
    """Raised when the generated SQL is unsafe or invalid by policy."""
    pass


def ensure_safe_sql(sql: str, max_rows: int = 500) -> str:
    """
    Enforce strict safety:
      - Only SELECT or WITH queries.
      - No semicolons (no multi-statements).
      - No dangerous keywords.
      - Ensure LIMIT <= max_rows.
    """
    if not sql or not sql.strip():
        raise SqlValidationError("Empty SQL.")

    # Remove trailing semicolon only (common LLM habit)
    sql_stripped = sql.strip()
    if sql_stripped.endswith(";"):
        sql_stripped = sql_stripped[:-1].rstrip()

    # Now reject any remaining semicolons to avoid multi-statements
    if ";" in sql_stripped:
        raise SqlValidationError("Semicolons / multiple statements are not allowed.")

    prefix = sql_stripped[:10].upper()
    if not (prefix.startswith("SELECT") or prefix.startswith("WITH")):
        raise SqlValidationError("Only SELECT or WITH queries are allowed.")

    upper_sql = sql_stripped.upper()
    for kw in FORBIDDEN_KEYWORDS:
        if kw in upper_sql:
            raise SqlValidationError(f"Forbidden keyword in SQL: {kw}")

    # Enforce LIMIT
    # If user already has LIMIT N and N > max_rows, clamp it.
    limit_pattern = re.compile(r"\bLIMIT\s+(\d+)", re.IGNORECASE)
    m = limit_pattern.search(sql_stripped)
    if m:
        current = int(m.group(1))
        if current > max_rows:
            sql_stripped = limit_pattern.sub(f"LIMIT {max_rows}", sql_stripped)
    else:
        sql_stripped = sql_stripped + f"\nLIMIT {max_rows}"

    return sql_stripped


def run_user_sql(sql: str, max_rows: int = 500) -> pd.DataFrame:
    """
    Validate and execute a user/LLM-generated SQL query, return a DataFrame.

    Raises:
      - SqlValidationError for policy violations.
      - SQLAlchemy / DB exceptions for actual DB errors.
    """
    safe_sql = ensure_safe_sql(sql, max_rows=max_rows)

    with engine.begin() as conn:
        result = conn.execute(text(safe_sql))
        df = pd.DataFrame(result.fetchall(), columns=result.keys())

    return df


if __name__ == "__main__":
    # Simple smoke test
    try:
        test = "SELECT profile_id, float_id, latitude, longitude FROM profiles ORDER BY profile_id LIMIT 5;"
        df_test = run_user_sql(test)
        print(df_test.head())
        print("✅ sql_guard self-test OK")
    except Exception as e:
        print("❌ sql_guard self-test FAILED:", e)
