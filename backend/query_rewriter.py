# backend/query_rewriter.py

import json
import google.generativeai as genai

from .config import get_gemini_api_key

REWRITE_MODEL = "gemini-2.5-flash"

SYSTEM = """
You rewrite messy user queries about Indian Ocean Argo/BGC data
into clear, explicit English questions that mention:

- variables (temperature_c, salinity_psu, doxy_umol_kg, chlorophyll_mg_m3, nitrate_umol_kg, ph_total)
  using either their column names or very clear synonyms,
- time ranges (explicit years/months),
- depth or pressure ranges when implied,
- spatial region (Indian Ocean, Arabian Sea, Bay of Bengal, equator, etc.),
- any filters on float ids, data_mode, has_bgc.

Do NOT write SQL.
Do NOT add anything the user did not imply.
Just produce one clearly written query, in English.
Return ONLY plain text, no JSON, no quotes.
"""

_model = None


def _get_model():
    global _model
    if _model is not None:
        return _model

    api_key = get_gemini_api_key()
    genai.configure(api_key=api_key)
    _model = genai.GenerativeModel(REWRITE_MODEL)
    return _model


def rewrite_query(user_query: str) -> str:
    """
    Normalize free-form user query into a clearer NL query that
    can be fed into RAG + NL→SQL.
    """
    try:
        model = _get_model()
        prompt = f"{SYSTEM}\n\nUSER QUERY:\n{user_query}\n\nREWRITTEN:"
        resp = model.generate_content(prompt)
        text = resp.text.strip()
        return text or user_query
    except Exception:
        # If anything fails, fall back to original
        return user_query
