# backend/api.py

from typing import Any, Dict, Optional

import pandas as pd
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .ai_pipeline import answer_question
from .mcp_tools import tool_describe_dataframe, build_schema_from_df, tool_infer_viz_intent

app = FastAPI(title="FloatChat Backend API")

# CORS so Dash frontend can call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # for local dev; tighten later if needed
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root() -> Dict[str, str]:
    return {"message": "FloatChat backend alive"}


@app.post("/ask")
def ask_api(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main endpoint called by the Dash frontend.

    Expects JSON:
      { "query": "<user text>" }

    Returns a JSON shape:

      {
        "ok": bool,
        "explanation": str,
        "sql": str | null,
        "error": str | null,
        "data": {
          "rows": [ ... ],
          "summary": { ... },
          "schema": { ... }
        },
        "viz": { ... },
        "history": [...]
      }
    """
    user_query: str = (payload.get("query") or "").strip()
    if not user_query:
        return {
            "ok": False,
            "explanation": "Empty query.",
            "sql": None,
            "error": "Empty query.",
            "data": {
                "rows": None,
                "summary": {"empty": True},
                "schema": {"columns": []},
            },
            "viz": None,
            "history": [],
        }

    result = answer_question(user_query)

    df: Optional[pd.DataFrame] = result.get("df")
    if isinstance(df, pd.DataFrame) and not df.empty:
        rows = df.to_dict(orient="records")
        summary = tool_describe_dataframe(df)
        schema = build_schema_from_df(df)
        viz = tool_infer_viz_intent(df, result.get("final_sql") or "", user_query)
    else:
        rows = None
        summary = {"empty": True}
        schema = {"columns": []}
        viz = None

    return {
        "ok": result.get("ok", False),
        "explanation": result.get("final_explanation"),
        "sql": result.get("final_sql"),
        "error": result.get("error"),
        "data": {
            "rows": rows,
            "summary": summary,
            "schema": schema,
        },
        "viz": viz,
        "history": result.get("history", []),
    }
