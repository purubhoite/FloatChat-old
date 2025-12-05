# backend/ai_pipeline.py

from typing import Any, Dict, Optional
import json

import pandas as pd

from .nl2sql_agent import generate_sql, repair_sql
from .sql_guard import run_user_sql
from .mcp_tools import tool_describe_dataframe
from .llm import call_llm_json

MAX_ROWS_FOR_ASK = 5000
def answer_question(
    user_query: str,
    image: Optional[Dict[str, Any]] = None,  # kept for future multimodal use
    max_repair_attempts: int = 1,
) -> Dict[str, Any]:
    """
    Top-level AI pipeline.

    Steps:
      1. NL → SQL (generate_sql)
      2. Execute SQL safely (run_user_sql)
      3. If error, repair (repair_sql)
      4. Summarize result DataFrame (tool_describe_dataframe)
      5. Ask the configured LLM backend (Gemini or local Ollama via call_llm_json)
         to produce a narrative explanation.

    Returns:
      {
        "ok": bool,
        "final_sql": str | None,
        "final_explanation": str,
        "df": DataFrame | None,
        "error": str | None,
        "history": [
          {
            "stage": "initial" | "repair_n",
            "sql": str,
            "explanation": str,
            "error": str | None
          },
          ...
        ]
      }
    """
    history = []

    # 1) Initial NL → SQL
    plan = generate_sql(user_query)
    sql = (plan.get("sql") or "").strip()
    explanation = (plan.get("explanation") or "").strip()

    if not sql:
        msg = "Model did not produce any SQL for this question."
        history.append(
            {
                "stage": "initial",
                "sql": sql,
                "explanation": explanation,
                "error": msg,
            }
        )
        return {
            "ok": False,
            "final_sql": None,
            "final_explanation": explanation or msg,
            "df": None,
            "error": msg,
            "history": history,
        }

    # 2) Try executing the SQL, with optional repair
    try:
        df = run_user_sql(sql,max_rows=MAX_ROWS_FOR_ASK)
        history.append(
            {
                "stage": "initial",
                "sql": sql,
                "explanation": explanation,
                "error": None,
            }
        )
        final_sql = sql
        final_explanation = explanation
        error: Optional[str] = None
    except Exception as e:
        last_sql = sql
        last_error = str(e)
        history.append(
            {
                "stage": "initial",
                "sql": sql,
                "explanation": explanation,
                "error": last_error,
            }
        )

        df = None
        final_sql = None
        final_explanation = explanation
        error = last_error

        # Attempt repairs
        for attempt in range(1, max_repair_attempts + 1):
            repair_plan = repair_sql(user_query, last_sql, last_error)
            repaired_sql = (repair_plan.get("sql") or "").strip()
            repaired_explanation = (repair_plan.get("explanation") or "").strip()

            if not repaired_sql:
                history.append(
                    {
                        "stage": f"repair_{attempt}",
                        "sql": repaired_sql,
                        "explanation": repaired_explanation,
                        "error": "Repair step did not produce SQL.",
                    }
                )
                break

            try:
                df = run_user_sql(repaired_sql,max_rows=MAX_ROWS_FOR_ASK)
                history.append(
                    {
                        "stage": f"repair_{attempt}",
                        "sql": repaired_sql,
                        "explanation": repaired_explanation,
                        "error": None,
                    }
                )
                final_sql = repaired_sql
                # Prefer the repaired explanation if present
                final_explanation = repaired_explanation or explanation
                error = None
                break
            except Exception as e2:
                last_sql = repaired_sql
                last_error = str(e2)
                history.append(
                    {
                        "stage": f"repair_{attempt}",
                        "sql": repaired_sql,
                        "explanation": repaired_explanation,
                        "error": last_error,
                    }
                )
                error = last_error

    # If still failing after repairs
    if error is not None or df is None:
        return {
            "ok": False,
            "final_sql": final_sql,
            "final_explanation": final_explanation
            or "Could not generate a working SQL query.",
            "df": None,
            "error": error,
            "history": history,
        }

    # 3) Summarize DF and ask the configured LLM backend for a narrative explanation
    summary = tool_describe_dataframe(df)

    # We ask the model to respond with: {"explanation": "..."}
    explain_prompt = f"""
You are an oceanographer explaining Indian Ocean ARGO + BGC data.

User question:
{user_query}

A SQL query was executed against the Indian Ocean Argo database.
Here is a brief description of that SQL:
{final_explanation}

Here is a JSON summary of the resulting data (time range, basic stats, etc.):
{summary}

Please provide a clear, concise, scientifically sound explanation of what these data
say about the ocean conditions, including BGC parameters (oxygen, chlorophyll, nitrate, pH)
if present. Mention any limitations due to QC filters or missing adjusted data.
The audience is a non-technical decision-maker.

Return your answer as a JSON object with exactly one key:
{{ "explanation": "..." }}
"""

    try:
        json_text = call_llm_json(explain_prompt)
        parsed = json.loads(json_text)
        refined_explanation = (
            (parsed.get("explanation") or "").strip() or final_explanation
        )
    except Exception:
        # Fallback: use SQL explanation only
        refined_explanation = final_explanation

    return {
        "ok": True,
        "final_sql": final_sql,
        "final_explanation": refined_explanation,
        "df": df,
        "error": None,
        "history": history,
    }
