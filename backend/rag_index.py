# backend/rag_index.py

"""
RAG over schema + tools for NL→SQL + plotting.

Design goals:
- Use a pluggable embeddings backend (Gemini or local) + ChromaDB (persistent on disk)
- Index multiple *typed* docs: schema DSL, join graph, examples, repair tips, etc.
- Always return a context that:
    - Includes the structured SCHEMA_DSL and JOIN_GRAPH.
    - Includes variable categories & NL synonyms.
    - Adds a few most-relevant extra docs (examples, prose, repair tips, etc.).
"""

from __future__ import annotations

from typing import Callable, List, Dict, Any, Optional

import chromadb

from .embeddings import get_embedder

from .schema_docs import (
    SCHEMA_TEXT,
    MCP_TOOLS_TEXT,
    SCHEMA_DSL,
    JOIN_GRAPH,
    VARIABLE_CATEGORIES,
    NATURAL_LANGUAGE_SYNONYMS,
    EXAMPLE_SQL,
    PLOT_INTENT_SPEC,
    QUERY_REPAIR_TIPS,
)

# Where to persist the Chroma DB
VECTOR_STORE_DIR = "vector_store"
COLLECTION_NAME = "argo_schema_docs"
#EMBED_MODEL = "models/text-embedding-004"

# Simple module-level caches
_client: Optional[chromadb.ClientAPI] = None
_collection: Optional[chromadb.Collection] = None



# ----------------------------------------------------------------------
# 2) Chroma collection helper
# ----------------------------------------------------------------------
def _get_collection() -> chromadb.Collection:
    """
    Return the Chroma collection, creating the persistent client if needed.
    """
    global _client, _collection
    if _collection is not None:
        return _collection

    _client = chromadb.PersistentClient(path=VECTOR_STORE_DIR)
    _collection = _client.get_or_create_collection(COLLECTION_NAME)
    return _collection


# ----------------------------------------------------------------------
# 3) Build / ensure vector index
# ----------------------------------------------------------------------
def _build_docs() -> List[Dict[str, Any]]:
    """
    Build the list of logical 'documents' to embed and store in Chroma.

    Each doc has:
      - id: unique string
      - text: the content to embed
      - meta: metadata with 'type' and maybe 'section'
    """
    docs: List[Dict[str, Any]] = []

    # 1) Prose schema
    docs.append(
        {
            "id": "schema_prose",
            "text": SCHEMA_TEXT,
            "meta": {"type": "schema_prose", "section": "overview"},
        }
    )

    # 2) Structured DSL
    docs.append(
        {
            "id": "schema_dsl",
            "text": SCHEMA_DSL,
            "meta": {"type": "schema_dsl"},
        }
    )

    # 3) Join graph
    docs.append(
        {
            "id": "join_graph",
            "text": JOIN_GRAPH,
            "meta": {"type": "join_graph"},
        }
    )

    # 4) Variable categories
    docs.append(
        {
            "id": "variable_categories",
            "text": VARIABLE_CATEGORIES,
            "meta": {"type": "variables"},
        }
    )

    # 5) NL synonyms
    docs.append(
        {
            "id": "nl_synonyms",
            "text": NATURAL_LANGUAGE_SYNONYMS,
            "meta": {"type": "synonyms"},
        }
    )

    # 6) Example SQL
    docs.append(
        {
            "id": "example_sql",
            "text": EXAMPLE_SQL,
            "meta": {"type": "examples"},
        }
    )

    # 7) Plot intent spec
    docs.append(
        {
            "id": "plot_intent_spec",
            "text": PLOT_INTENT_SPEC,
            "meta": {"type": "plot_intent"},
        }
    )

    # 8) SQL repair tips
    docs.append(
        {
            "id": "query_repair_tips",
            "text": QUERY_REPAIR_TIPS,
            "meta": {"type": "repair_tips"},
        }
    )

    # 9) MCP / tools description
    docs.append(
        {
            "id": "mcp_tools",
            "text": MCP_TOOLS_TEXT,
            "meta": {"type": "mcp"},
        }
    )

    return docs


def _ensure_index_built() -> None:
    """
    Build the vector index once if empty.

    This is intentionally simple: a small number of high-quality
    'reference' docs (schema, DSL, examples, tools).
    """
    collection = _get_collection()
    if collection.count() > 0:
        return

    embed = get_embedder()
    docs = _build_docs()

    ids: List[str] = []
    texts: List[str] = []
    metas: List[Dict[str, Any]] = []
    embeddings: List[List[float]] = []

    for doc in docs:
        ids.append(doc["id"])
        texts.append(doc["text"])
        metas.append(doc["meta"])
        embeddings.append(embed(doc["text"]))

    collection.add(
        ids=ids,
        documents=texts,
        metadatas=metas,
        embeddings=embeddings,
    )


# ----------------------------------------------------------------------
# 4) RAG query
# ----------------------------------------------------------------------
def query_rag(user_query: str, n_results: int = 7) -> str:
    """
    Retrieve schema/context text for a given natural-language question.

    Returns a single concatenated text block that should be given to the
    NL→SQL model as context.

    Strategy:
      - Ensure vector index is built.
      - Embed the user query, ask Chroma for top-k docs.
      - Always include:
          * SCHEMA_DSL
          * JOIN_GRAPH
          * VARIABLE_CATEGORIES
          * NATURAL_LANGUAGE_SYNONYMS
      - Then append the most relevant retrieved docs (examples, prose,
        repair tips, MCP tools, plot intent) up to n_results.
    """
    _ensure_index_built()
    collection = _get_collection()
    embed = get_embedder()

    try:
        q_emb = embed(user_query)
    except Exception as e:
        # If embedding fails for some reason, fall back to raw concatenation
        base_blocks = [
            "### SCHEMA DSL\n" + SCHEMA_DSL,
            "### JOIN GRAPH\n" + JOIN_GRAPH,
            "### VARIABLE CATEGORIES\n" + VARIABLE_CATEGORIES,
            "### NATURAL LANGUAGE SYNONYMS\n" + NATURAL_LANGUAGE_SYNONYMS,
            "### MCP TOOLS\n" + MCP_TOOLS_TEXT,
        ]
        return "\n\n---\n\n".join(base_blocks)

    res = collection.query(
        query_embeddings=[q_emb],
        n_results=n_results,
    )

    docs = res.get("documents", [[]])[0] if res else []
    metas = res.get("metadatas", [[]])[0] if res else []

    # Base context: always present
    base_blocks: List[str] = [
        "### SCHEMA DSL\n" + SCHEMA_DSL,
        "### JOIN GRAPH\n" + JOIN_GRAPH,
        "### VARIABLE CATEGORIES\n" + VARIABLE_CATEGORIES,
        "### NATURAL LANGUAGE SYNONYMS\n" + NATURAL_LANGUAGE_SYNONYMS,
    ]

    # Bucket retrieved docs by type
    schema_prose_docs: List[str] = []
    example_docs: List[str] = []
    repair_docs: List[str] = []
    plot_docs: List[str] = []
    mcp_docs: List[str] = []
    other_docs: List[str] = []

    for doc, meta in zip(docs, metas):
        t = (meta or {}).get("type")

        # We already inline DSL + join + variables + synonyms above,
        # so skip those here to avoid duplication.
        if t in {"schema_dsl", "join_graph", "variables", "synonyms"}:
            continue

        if t == "schema_prose":
            schema_prose_docs.append(doc)
        elif t == "examples":
            example_docs.append(doc)
        elif t == "repair_tips":
            repair_docs.append(doc)
        elif t == "plot_intent":
            plot_docs.append(doc)
        elif t == "mcp":
            mcp_docs.append(doc)
        else:
            other_docs.append(doc)

    # Compose a final list in a sensible priority order:
    # some schema prose, some examples, maybe repair tips, plot spec, mcp.
    extra_blocks: List[str] = []

    extra_blocks.extend(schema_prose_docs[:1])   # one prose overview
    extra_blocks.extend(example_docs[:2])        # a couple of examples
    extra_blocks.extend(repair_docs[:1])         # repair guidance
    extra_blocks.extend(plot_docs[:1])           # plot intent spec
    extra_blocks.extend(mcp_docs[:1])            # tools description
    extra_blocks.extend(other_docs[:2])          # any remaining useful bits

    # If for some reason nothing came back, fall back to minimal but complete pack
    if not extra_blocks:
        extra_blocks = [
            "### SCHEMA PROSE\n" + SCHEMA_TEXT,
            "### EXAMPLE SQL PATTERNS\n" + EXAMPLE_SQL,
            "### SQL REPAIR TIPS\n" + QUERY_REPAIR_TIPS,
            "### MCP TOOLS\n" + MCP_TOOLS_TEXT,
            "### PLOT INTENT SPEC\n" + PLOT_INTENT_SPEC,
        ]

    # Cap total extra blocks to n_results (ish)
    extra_blocks = extra_blocks[: max(1, n_results)]

    # Always make sure MCP tools and plot spec are *somewhere* if user is asking
    # for plots or tools. Very cheap heuristic: substring search.
    uq_lower = user_query.lower()
    needs_plot = any(w in uq_lower for w in ["plot", "profile", "time series", "map", "trajectory", "section"])
    needs_tools = any(w in uq_lower for w in ["sql", "query", "tool", "mcp"])

    if needs_plot and not any("PLOT INTENT" in b for b in extra_blocks):
        extra_blocks.append("### PLOT INTENT SPEC\n" + PLOT_INTENT_SPEC)

    if needs_tools and not any("MCP TOOLS" in b for b in extra_blocks):
        extra_blocks.append("### MCP TOOLS\n" + MCP_TOOLS_TEXT)

    final_blocks = base_blocks + extra_blocks
    return "\n\n---\n\n".join(final_blocks)
