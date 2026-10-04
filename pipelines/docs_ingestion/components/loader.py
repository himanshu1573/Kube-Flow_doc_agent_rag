"""
Docs Ingestion — Loader Component

Loads embedded docs chunks into the Milvus docs_collection using primary-key
upserts and shared collection helpers.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Dict, List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from pymilvus import utility

from backend.schemas.docs_collection_schema import (
    COLLECTION_NAME,
    get_docs_fields,
    get_docs_index_params,
)
from pipelines.shared.milvus_utils import connect, create_collection_if_not_exists, upsert_batch

logger = logging.getLogger(__name__)


def should_recreate_collection() -> bool:
    """Return whether docs_collection should be dropped before loading."""
    return os.environ.get("MILVUS_DROP_EXISTING_DOCS", "false").lower() == "true"


def load_to_milvus(
    chunks: List[Dict[str, object]],
    collection_name: str | None = None,
) -> Dict[str, int]:
    """Load embedded docs chunks into Milvus."""
    col_name = collection_name or COLLECTION_NAME

    connect()

    if should_recreate_collection() and utility.has_collection(col_name):
        utility.drop_collection(col_name)
        logger.info("Dropped existing docs collection %s for a clean reload", col_name)

    collection = create_collection_if_not_exists(
        collection_name=col_name,
        fields=get_docs_fields(),
        description="Kubeflow docs chunks for RAG retrieval",
        index_field="embedding",
        index_params=get_docs_index_params(),
    )

    rows = []
    for chunk in chunks:
        if "embedding" not in chunk:
            continue

        rows.append(
            {
                "chunk_id": str(chunk["chunk_id"])[:128],
                "source_url": str(chunk.get("source_url", ""))[:512],
                "page_title": str(chunk.get("page_title", ""))[:256],
                "heading": str(chunk.get("heading", ""))[:256],
                "parent_heading": str(chunk.get("parent_heading", ""))[:256],
                "heading_path": str(chunk.get("heading_path", ""))[:512],
                "breadcrumb_path": str(chunk.get("breadcrumb_path", ""))[:256],
                "section": str(chunk.get("section", ""))[:128],
                "chunk_type": str(chunk.get("chunk_type", "concept"))[:32],
                "chunk_text": str(chunk.get("chunk_text", ""))[:16384],
                "token_count": int(chunk.get("token_count", 0)),
                "chunk_index": int(chunk.get("chunk_index", 0)),
                "crawled_at": str(chunk.get("crawled_at", ""))[:64],
                "embedding": chunk["embedding"],
            }
        )

    if not rows:
        return {"inserted": 0, "failed": 0, "total": 0, "skipped": len(chunks)}

    summary = upsert_batch(collection, rows, batch_size=100)
    summary["skipped"] = len(chunks) - len(rows)
    logger.info(
        "Docs ingestion: %d inserted, %d failed, %d skipped",
        summary["inserted"],
        summary["failed"],
        summary["skipped"],
    )
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logger.info("Docs loader smoke test requires Milvus to be available.")
