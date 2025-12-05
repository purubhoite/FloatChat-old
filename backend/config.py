# backend/config.py

import os
from dotenv import load_dotenv

# Load environment variables from .env file (if present)
load_dotenv()

def get_gemini_api_key() -> str:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set in environment or .env file.")
    return key
