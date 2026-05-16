# backend/ai_pipeline.py

from typing import Any, Dict, Optional
import json

import pandas as pd

from .nl2sql_agent import generate_sql, repair_sql
from .sql_guard import run_user_sql
from .mcp_tools import tool_describe_dataframe
from .llm import call_llm_json
from .intent_classifier import classify_query_intent
from .knowledge_base import get_knowledge_answer
from .date_rewriter import get_date_context_for_prompt

MAX_ROWS_FOR_ASK = 5000


def _generate_sql_for_plan(plan: Dict[str, Any], user_query: str) -> Optional[str]:
    """
    Generate SQL from a plot_plan or map_plan if SQL wasn't already provided.
    
    This handles cases where the LLM returns a plan but didn't include SQL.
    We construct a simple SQL query based on the plan's filters and variables.
    """
    if not plan:
        return None
    
    # Extract plan details (could be dict or parsed from explanation)
    if isinstance(plan, dict):
        plan_data = plan
    else:
        return None
    
    # Check if plan already indicates SQL was generated
    if plan_data.get("requires_sql") is False:
        return None
    
    # Extract filter information from plan
    filters = plan_data.get("filters", {})
    variables = plan_data.get("variables", [])
    plan_type = plan_data.get("type", "profile")
    
    # Build a base query for visualization
    # This is a fallback when LLM didn't generate SQL directly
    
    # Core columns always needed
    select_cols = [
        "p.profile_id",
        "p.float_id", 
        "p.cycle_number",
        "p.profile_time",
        "p.latitude",
        "p.longitude",
        "m.depth_m",
    ]
    
    # Add requested variables
    var_mapping = {
        "oxygen": "m.doxy_umol_kg",
        "doxy": "m.doxy_umol_kg",
        "doxy_umol_kg": "m.doxy_umol_kg",
        "chlorophyll": "m.chlorophyll_mg_m3",
        "chla": "m.chlorophyll_mg_m3",
        "chlorophyll_mg_m3": "m.chlorophyll_mg_m3",
        "nitrate": "m.nitrate_umol_kg",
        "nitrate_umol_kg": "m.nitrate_umol_kg",
        "ph": "m.ph_total",
        "ph_total": "m.ph_total",
        "temperature": "m.temperature_c",
        "temperature_c": "m.temperature_c",
        "salinity": "m.salinity_psu",
        "salinity_psu": "m.salinity_psu",
    }
    
    qc_conditions = []
    for var in variables:
        var_lower = var.lower()
        if var_lower in var_mapping:
            col = var_mapping[var_lower]
            select_cols.append(col)
            # Add QC conditions for BGC variables
            base_name = col.split(".")[-1]  # e.g., "doxy_umol_kg"
            qc_name = base_name.replace("_umol_kg", "").replace("_mg_m3", "").replace("_c", "").replace("_psu", "").replace("_total", "")
            if "doxy" in base_name:
                qc_conditions.append(f"m.doxy_source = 'ADJUSTED' AND m.doxy_qc = 1")
            elif "chlorophyll" in base_name:
                qc_conditions.append(f"m.chla_source = 'ADJUSTED' AND m.chla_qc = 1")
            elif "nitrate" in base_name:
                qc_conditions.append(f"m.nitrate_source = 'ADJUSTED' AND m.nitrate_qc = 1")
            elif "ph" in base_name:
                qc_conditions.append(f"m.ph_source = 'ADJUSTED' AND m.ph_qc = 1")
            elif "temperature" in base_name:
                qc_conditions.append(f"m.temperature_source = 'ADJUSTED' AND m.temperature_qc = 1")
            elif "salinity" in base_name:
                qc_conditions.append(f"m.salinity_source = 'ADJUSTED' AND m.salinity_qc = 1")
    
    # If no specific variables, add common BGC ones
    if not variables:
        select_cols.extend(["m.doxy_umol_kg", "m.nitrate_umol_kg", "m.chlorophyll_mg_m3"])
    
    # Build WHERE conditions
    where_conditions = ["1=1"]
    
    # Region filter
    region = filters.get("region", "").lower()
    if "arabian" in region:
        where_conditions.append("p.latitude BETWEEN 0 AND 30 AND p.longitude BETWEEN 45 AND 75")
    elif "bengal" in region:
        where_conditions.append("p.latitude BETWEEN 0 AND 25 AND p.longitude BETWEEN 80 AND 100")
    elif "equator" in region:
        where_conditions.append("ABS(p.latitude) <= 5")
    
    # Time filter
    start_date = filters.get("start_date") or filters.get("time_start")
    end_date = filters.get("end_date") or filters.get("time_end")
    if start_date:
        where_conditions.append(f"p.profile_time >= '{start_date}'")
    if end_date:
        where_conditions.append(f"p.profile_time <= '{end_date}'")
    
    # BGC filter
    if any(v.lower() in ["oxygen", "doxy", "chlorophyll", "nitrate", "ph"] for v in variables):
        where_conditions.append("p.has_bgc = TRUE")
    
    # Add QC conditions
    where_conditions.extend(qc_conditions)
    
    # Construct SQL
    sql = f"""
SELECT {', '.join(select_cols)}
FROM profiles p
JOIN measurements m ON m.profile_id = p.profile_id
WHERE {' AND '.join(where_conditions)}
ORDER BY p.profile_time, p.latitude, p.longitude, m.depth_m
LIMIT 5000
""".strip()
    
    return sql


def answer_question(
    user_query: str,
    image: Optional[Dict[str, Any]] = None,  # kept for future multimodal use
    conversation_history: Optional[list] = None,
    max_repair_attempts: int = 1,
) -> Dict[str, Any]:
    """
    Top-level AI pipeline.

    Steps:
      0. Classify query intent (knowledge vs data query)
      0a. If knowledge query, return answer from knowledge base directly
      1. NL → SQL/Plan (generate_sql, optionally with conversation context)
      1a. Handle plot_plan/map_plan modes - generate SQL if needed
      2. Execute SQL safely (run_user_sql)
      3. If error, repair (repair_sql)
      4. Summarize result DataFrame (tool_describe_dataframe)
      5. Ask the configured LLM backend to produce a narrative explanation

    Args:
      user_query: Current question from user
      image: Optional image for multimodal use
      conversation_history: List of previous messages
      max_repair_attempts: Number of SQL repair attempts

    Returns:
      {
        "ok": bool,
        "mode": str,               # "sql" | "plot_plan" | "map_plan" | "knowledge"
        "final_sql": str | None,
        "final_explanation": str,
        "plan": dict | None,       # Visualization plan for plot/map modes
        "df": DataFrame | None,
        "error": str | None,
        "history": [...]
      }
    """
    if conversation_history is None:
        conversation_history = []
    
    history = []

    # 0) Classify query intent - route knowledge queries to knowledge base
    intent = classify_query_intent(user_query)
    
    if intent == "knowledge":
        # Handle knowledge/definition queries directly without SQL
        try:
            answer = get_knowledge_answer(user_query, conversation_history)
        except Exception as e:
            answer = f"I apologize, but I couldn't retrieve that information. Error: {str(e)}"
        
        return {
            "ok": True,
            "mode": "knowledge",
            "final_sql": None,
            "final_explanation": answer,
            "plan": None,
            "df": None,
            "error": None,
            "history": [],
        }

    # 1) Initial NL → SQL/Plan (pass conversation context) - for data queries
    plan_result = generate_sql(user_query, conversation_history=conversation_history)
    mode = plan_result.get("mode", "sql")
    sql = (plan_result.get("sql") or "").strip() if plan_result.get("sql") else ""
    plan = plan_result.get("plan")
    explanation = (plan_result.get("explanation") or "").strip()

    # 1a) Handle plot_plan/map_plan modes - ensure we have SQL
    if mode in ("plot_plan", "map_plan") and not sql:
        # Try to generate SQL from the plan
        generated_sql = _generate_sql_for_plan(plan, user_query)
        if generated_sql:
            sql = generated_sql

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
            "mode": mode,
            "final_sql": None,
            "final_explanation": explanation or msg,
            "plan": plan,
            "df": None,
            "error": msg,
            "history": history,
        }

    # 2) Try executing the SQL, with optional repair
    try:
        df = run_user_sql(sql, max_rows=MAX_ROWS_FOR_ASK)
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
                df = run_user_sql(repaired_sql, max_rows=MAX_ROWS_FOR_ASK)
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
            "mode": mode,
            "final_sql": final_sql,
            "final_explanation": final_explanation
            or "Could not generate a working SQL query.",
            "plan": plan,
            "df": None,
            "error": error,
            "history": history,
        }

    # 3) Summarize DF and ask the configured LLM backend for a narrative explanation
    summary = tool_describe_dataframe(df)

    # Build conversation context for the LLM
    conversation_context = ""
    if conversation_history:
        conversation_context = "\n\nPrevious conversation:\n"
        for msg in conversation_history[-4:]:  # Include last 4 messages for context
            role = "User" if msg.get("role") == "user" else "Assistant"
            text = msg.get("text", "")
            conversation_context += f"{role}: {text}\n"

    # Get current date context
    date_context = get_date_context_for_prompt()

    # We ask the model to respond with: {"explanation": "..."}
    explain_prompt = f"""
You are an oceanographer explaining Indian Ocean ARGO + BGC data.
{conversation_context}
{date_context}

Current user question:
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
        "mode": mode,
        "final_sql": final_sql,
        "final_explanation": refined_explanation,
        "plan": plan,
        "df": df,
        "error": None,
        "history": history,
    }
