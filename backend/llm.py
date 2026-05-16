# backend/llm.py

"""
LLM backend module supporting both Gemini API and local Ollama models.
Controlled by LLM_BACKEND environment variable.
"""

import os
from typing import Dict, Any, Literal

# Backend configuration - defaults to local_ollama
LLM_BACKEND: Literal["gemini", "local_ollama"] = os.getenv("LLM_BACKEND", "gemini")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3:instruct")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


# ---------------- Gemini backend ----------------
def _call_gemini_json(prompt: str) -> str:
    """
    Call Gemini and return a JSON string (model is instructed to respond with JSON).
    """
    import google.generativeai as genai
    from .config import get_gemini_api_key

    genai.configure(api_key=get_gemini_api_key())
    model = genai.GenerativeModel(
        GEMINI_MODEL,
        generation_config={"response_mime_type": "application/json"},
    )
    resp = model.generate_content(prompt)
    # Gemini already returns text that should be a JSON string
    return resp.text


# ---------------- Ollama backend (local LLM) ----------------
def _call_ollama_json(prompt: str) -> str:
    """
    Call a local Ollama model (e.g., llama3) and ask it to respond with JSON.

    Requirements:
      - `ollama serve` running locally
      - model pulled: `ollama pull llama3`
    """
    import requests

    # We embed strong instructions to return ONLY JSON
    full_prompt = (
        "You are a backend SQL planning assistant.\n"
        "You MUST respond with ONLY a single valid JSON object, no markdown, no text before or after.\n"
        "The JSON must follow exactly the schema described below.\n\n"
        + prompt
    )

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": full_prompt,
        "format": "json",   # ask Ollama to enforce JSON
        "stream": False,
    }

    r = requests.post(OLLAMA_URL, json=payload, timeout=120)
    r.raise_for_status()
    data: Dict[str, Any] = r.json()
    # Ollama returns response in "response"
    return data.get("response", "")
    

# ---------------- Public entrypoint ----------------
def call_llm_json(prompt: str) -> str:
    """
    Return a JSON string from the configured backend.
    The caller will do json.loads(...) on this.
    
    Backend controlled by LLM_BACKEND env var:
    - "local_ollama" (default): Uses local Ollama model
    - "gemini": Uses Google Gemini API
    """
    if LLM_BACKEND == "gemini":
        return _call_gemini_json(prompt)
    else:
        return _call_ollama_json(prompt)
