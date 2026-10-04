"""
Docs Ingestion — Embedder Component

Embeds docs chunks using the shared embedding client so docs and code pipelines
stay aligned on model configuration.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Dict, Iterable, List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from pipelines.shared.embedding_utils import EmbeddingClient

logger = logging.getLogger(__name__)


def build_embedding_text(chunk: Dict[str, object]) -> str:
    """Build a retrieval-oriented embedding payload for a docs chunk."""
    parts = [
        f"# Title: {chunk.get('page_title', '')}",
        f"# Section: {chunk.get('section', '')}",
        f"# Heading: {chunk.get('heading', '')}",
        f"# Parent Heading: {chunk.get('parent_heading', '')}",
        f"# Heading Path: {chunk.get('heading_path', '')}",
        f"# Breadcrumb: {chunk.get('breadcrumb_path', '')}",
        f"# Chunk Type: {chunk.get('chunk_type', '')}",
        f"# URL: {chunk.get('source_url', '')}",
        "",
        str(chunk.get("chunk_text", "")),
    ]
    return "\n".join(parts).strip()


def embed_docs_chunks(
    chunks: List[Dict[str, object]],
    batch_size: int = 32,
) -> List[Dict[str, object]]:
    """Embed docs chunks and attach vectors."""
    if not chunks:
        logger.warning("No docs chunks to embed.")
        return []

    client = EmbeddingClient(batch_size=batch_size)
    texts = [build_embedding_text(chunk) for chunk in chunks]
    embeddings = client.embed_texts(texts, purpose="passage")

    for chunk, embedding in zip(chunks, embeddings):
        chunk["embedding"] = embedding

    logger.info("Embedded %d docs chunks using %s", len(chunks), client.model_name)
    return chunks


def load_chunks(input_path: str) -> List[Dict[str, object]]:
    """Load chunk JSONL records."""
    chunks: List[Dict[str, object]] = []
    with open(input_path, "r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                chunks.append(json.loads(line))
    return chunks


def save_embedded_chunks(chunks: Iterable[Dict[str, object]], output_path: str) -> None:
    """Save embedded chunks to JSONL."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(chunk, ensure_ascii=False) + "\n")
    logger.info("Saved embedded docs chunks to %s", output_path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    sample = [
        {
            "chunk_id": "test",
            "source_url": "https://www.kubeflow.org/docs/",
            "page_title": "Docs",
            "section": "docs",
            "heading": "Overview",
            "chunk_text": "Kubeflow docs overview.",
        }
    ]
    result = embed_docs_chunks(sample)
    logger.info("Embedding dimension: %d", len(result[0]["embedding"]))
