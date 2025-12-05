# backend/embeddings.py

from typing import List, Callable, Literal, Optional
import os

# Which backend to use for embeddings: "gemini" or "local"
EMBED_BACKEND: Literal["gemini", "local"] = os.getenv("EMBED_BACKEND", "local")

# Local model name (only used when EMBED_BACKEND == "local")
# You can override via env: LOCAL_EMBED_MODEL="all-MiniLM-L6-v2" etc.
LOCAL_EMBED_MODEL = os.getenv("LOCAL_EMBED_MODEL", "all-MiniLM-L6-v2")

# Global caches
_embedder_cache: Optional[Callable[[str], List[float]]] = None
_local_model = None


# ---------- Gemini backend ----------

def _get_gemini_embedder() -> Callable[[str], List[float]]:
    """
    Returns an embed(text) -> List[float] function using Gemini embeddings.
    """
    import google.generativeai as genai
    from .config import get_gemini_api_key

    api_key = get_gemini_api_key()
    genai.configure(api_key=api_key)

    EMBED_MODEL = "models/text-embedding-004"

    def embed(text: str) -> List[float]:
        # Be safe if something non-str is passed
        if not isinstance(text, str):
            text = str(text)

        resp = genai.embed_content(model=EMBED_MODEL, content=text)
        emb = resp.get("embedding")
        if isinstance(emb, dict):
            emb = emb.get("values") or emb.get("value")
        if not isinstance(emb, list):
            raise ValueError(f"Unexpected embedding format from Gemini: {resp}")
        return emb

    return embed


# ---------- Local backend (sentence-transformers) ----------

def _get_local_embedder() -> Callable[[str], List[float]]:
    """
    Returns an embed(text) -> List[float] function using a local
    sentence-transformers model (FAISS/Chroma friendly).
    """
    global _local_model
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as e:
        raise RuntimeError(
            "EMBED_BACKEND is set to 'local' but 'sentence-transformers' "
            "is not installed. Run: pip install sentence-transformers"
        ) from e

    if _local_model is None:
        # Loads once, kept in memory
        _local_model = SentenceTransformer(LOCAL_EMBED_MODEL)

    def embed(text: str) -> List[float]:
        if not isinstance(text, str):
            text = str(text)

        # normalize_embeddings=True gives unit-length vectors → better cosine similarity
        vec = _local_model.encode(text, normalize_embeddings=True)
        return vec.tolist()

    return embed


# ---------- Public getter ----------

def get_embedder() -> Callable[[str], List[float]]:
    """
    Main entrypoint: returns a function text -> embedding[list[float]].

    - Controlled by EMBED_BACKEND env var ("gemini" / "local").
    - Caches the chosen embedder for the lifetime of the process.
    """
    global _embedder_cache
    if _embedder_cache is not None:
        return _embedder_cache

    if EMBED_BACKEND == "local":
        _embedder_cache = _get_local_embedder()
    else:
        _embedder_cache = _get_gemini_embedder()

    return _embedder_cache
