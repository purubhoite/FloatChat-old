# backend/test_nl2sql.py

"""
Small CLI to test the NL→SQL pipeline end-to-end:

Flow:
  user_query
    → RAG (query_rag)
    → LLM (generate_sql)
    → sql_guard.ensure_safe_sql + run_user_sql
    → optional repair_sql on DB error

Run from repo root:
    python -m backend.test_nl2sql
"""

from __future__ import annotations

import traceback
from typing import List

import pandas as pd
from sqlalchemy.exc import SQLAlchemyError

from .nl2sql_agent import generate_sql, repair_sql
from .sql_guard import run_user_sql, SqlValidationError



# Some starter test queries you can tweak
TEST_QUERIES: List[str] = [
    "Show me temperature and salinity profiles near the equator in March 2023.",
    "Give me a time series of dissolved oxygen in the Arabian Sea over the last 6 months.",
    "List the floats with BGC data and their overall temperature and salinity ranges.",
    "Find the last 10 profiles in the Bay of Bengal with nitrate and chlorophyll data.",
    "Show a vertical profile of oxygen and temperature for any float near 10N, 60E in 2022.",
]


def run_single_query(user_query: str, max_rows: int = 200) -> None:
    print("\n" + "=" * 80)
    print(f"USER QUERY: {user_query}")
    print("=" * 80)

    # 1) Call NL→SQL agent
    plan = generate_sql(user_query)
    sql = plan.get("sql", "").strip()
    explanation = plan.get("explanation", "").strip()

    print("[Generated SQL]")
    print(sql or "(empty)")
    print("\n[Explanation]")
    print(explanation or "(none)")

    if not sql:
        print("\n⚠️ No SQL returned. Skipping execution.\n")
        return

    # 3) Validate + execute (with sql_guard)
    try:
        df = run_user_sql(sql, max_rows=max_rows)
        print(f"\n✅ SQL executed successfully. Returned {len(df)} rows.")
        # Show a small preview
        if not df.empty:
            print("\n[Result sample]")
            # Display up to first 10 rows and 10 columns
            with pd.option_context("display.max_rows", 10, "display.max_columns", 10):
                print(df.head(10))
        else:
            print("\n(Result is empty DataFrame.)")

    except SqlValidationError as ve:
        print("\n❌ SqlValidationError (policy violation):")
        print(str(ve))

    except SQLAlchemyError as db_err:
        print("\n❌ Database error when executing SQL:")
        print(str(db_err))

        # 4) Try automatic repair
        print("\nAttempting automatic SQL repair...\n")
        try:
            repair_plan = repair_sql(user_query, sql, str(db_err))
            repaired_sql = repair_plan.get("sql", "").strip()
            print("[Repaired SQL]")
            print(repaired_sql or "(empty)")
            print("\n[Repair explanation]")
            print(repair_plan.get("explanation", ""))

            if repaired_sql:
                df2 = run_user_sql(repaired_sql, max_rows=max_rows)
                print(f"\n✅ Repaired SQL executed successfully. Returned {len(df2)} rows.")
                if not df2.empty:
                    print("\n[Repaired Result sample]")
                    with pd.option_context("display.max_rows", 10, "display.max_columns", 10):
                        print(df2.head(10))
                else:
                    print("\n(Repaired result is empty DataFrame.)")
            else:
                print("\n⚠️ Repair produced no SQL, stopping here.")

        except Exception as repair_err:
            print("\n❌ Repair failed as well:")
            print(str(repair_err))
            traceback.print_exc()

    except Exception as e:
        print("\n❌ Unexpected error in test harness:")
        print(str(e))
        traceback.print_exc()


def run_batch_tests():
    print("=== Running batch NL→SQL tests ===")
    for q in TEST_QUERIES:
        run_single_query(q)


def interactive_shell():
    print("=== NL→SQL interactive shell ===")
    print("Type a natural language question about the ARGO/BGC data.")
    print("Type 'exit' or 'quit' to leave.\n")

    while True:
        try:
            user_query = input("NL query> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if not user_query:
            continue
        if user_query.lower() in {"exit", "quit"}:
            print("Bye.")
            break

        run_single_query(user_query)


if __name__ == "__main__":
    # 1) Run predefined tests
    run_batch_tests()

    # 2) Drop into an interactive loop so you can manually poke it
    print("\n\nNow entering interactive mode...\n")
    interactive_shell()
