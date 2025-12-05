# backend/index_schema_docs.py
"""
One-shot script to (re)build the base RAG index:
- schema DSL + prose
- join graph
- variable categories + NL synonyms
- example SQL patterns
- plot intent spec
- SQL repair tips
- MCP/tools description
"""

from typing import List, Dict, Any

import chromadb

from .rag_index import VECTOR_STORE_DIR, COLLECTION_NAME
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


def rebuild_base_index():
    client = chromadb.PersistentClient(path=VECTOR_STORE_DIR)
    collection = client.get_or_create_collection(COLLECTION_NAME)

    # Delete existing *base* docs, but keep float summaries (type="float_summary")
    collection.delete(
        where={
            "type": {
                "$in": [
                    "schema_prose",
                    "schema_dsl",
                    "join_graph",
                    "variables",
                    "synonyms",
                    "examples",
                    "plot_intent",
                    "repair_tips",
                    "mcp",
                ]
            }
        }
    )

    embed = get_embedder()

    docs: List[Dict[str, Any]] = []

    # 1) Schema prose (human readable overview)
    docs.append(
        {
            "id": "schema_prose",
            "text": SCHEMA_TEXT,
            "meta": {"type": "schema_prose", "section": "overview"},
        }
    )

    # 2) Structured schema DSL
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

    # 5) Natural language synonyms → column mappings
    docs.append(
        {
            "id": "nl_synonyms",
            "text": NATURAL_LANGUAGE_SYNONYMS,
            "meta": {"type": "synonyms"},
        }
    )

    # 6) Example SQL patterns
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

    # 8) Query repair tips
    docs.append(
        {
            "id": "query_repair_tips",
            "text": QUERY_REPAIR_TIPS,
            "meta": {"type": "repair_tips"},
        }
    )

    # 9) MCP tools description
    docs.append(
        {
            "id": "mcp_tools",
            "text": MCP_TOOLS_TEXT,
            "meta": {"type": "mcp"},
        }
    )

    ids = [d["id"] for d in docs]
    texts = [d["text"] for d in docs]
    metas = [d["meta"] for d in docs]
    embs = [embed(t) for t in texts]

    collection.add(ids=ids, documents=texts, metadatas=metas, embeddings=embs)

    print(f"✅ Rebuilt base RAG index with {len(docs)} documents.")


if __name__ == "__main__":
    rebuild_base_index()
