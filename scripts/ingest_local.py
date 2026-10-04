"""Run Phase 1 ingestion from your machine into any reachable Milvus.

Runs the same components as the Kubeflow Pipelines in ``pipelines/`` in one
local process. Point it at Milvus in Docker Compose or at a cluster Milvus
through ``kubectl port-forward``.

Examples:
    python scripts/ingest_local.py docs --max-pages 20
    python scripts/ingest_local.py code --repo https://github.com/kubeflow/manifests --branch master
    python scripts/ingest_local.py all --recreate

Connection and model settings come from the environment (MILVUS_HOST,
MILVUS_PORT, EMBEDDING_MODEL, DOCS_COLLECTION, CODE_COLLECTION). The API must
use the same EMBEDDING_MODEL as ingestion.
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logger = logging.getLogger("ingest_local")


def ingest_docs(base_url: str, max_pages: int, crawl_delay: float, collection: str) -> dict:
    from pipelines.docs_ingestion.components.chunker import chunk_pages
    from pipelines.docs_ingestion.components.crawler import crawl_docs
    from pipelines.docs_ingestion.components.embedder import embed_docs_chunks
    from pipelines.docs_ingestion.components.loader import load_to_milvus

    pages = crawl_docs(base_url=base_url, crawl_delay=crawl_delay, max_pages=max_pages)
    logger.info("docs: crawled %d pages", len(pages))
    chunks = chunk_pages(pages, chunk_size=500, chunk_overlap=50)
    logger.info("docs: produced %d chunks", len(chunks))
    summary = load_to_milvus(embed_docs_chunks(chunks), collection_name=collection)
    logger.info("docs: load summary %s", summary)
    return summary


def ingest_code(repo_url: str, branch: str, collection: str) -> dict:
    from pipelines.code_ingestion.components.ast_parser import parse_all_files
    from pipelines.code_ingestion.components.chunker import process_chunks
    from pipelines.code_ingestion.components.embedder import embed_code_chunks
    from pipelines.code_ingestion.components.loader import load_to_milvus
    from pipelines.code_ingestion.components.repo_cloner import clone_repo

    result = clone_repo(repo_url=repo_url, branch=branch)
    try:
        logger.info("code: cloned %s@%s (%d files)", repo_url, result["commit_sha"][:10], len(result["file_list"]))
        raw_chunks = parse_all_files(result["repo_dir"], result["file_list"], result["commit_sha"])
        processed = process_chunks(raw_chunks)
        logger.info("code: %d parsed -> %d processed chunks", len(raw_chunks), len(processed))
        summary = load_to_milvus(embed_code_chunks(processed), collection_name=collection)
        logger.info("code: load summary %s", summary)
        return summary
    finally:
        shutil.rmtree(result["repo_dir"], ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("target", choices=["docs", "code", "all"])
    parser.add_argument("--base-url", default="https://www.kubeflow.org")
    parser.add_argument("--max-pages", type=int, default=20, help="docs pages to crawl (default: 20)")
    parser.add_argument("--crawl-delay", type=float, default=0.1)
    parser.add_argument("--repo", default="https://github.com/kubeflow/manifests")
    parser.add_argument("--branch", default="master")
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="drop and recreate the target collections (required after changing EMBEDDING_MODEL)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.recreate:
        os.environ["MILVUS_DROP_EXISTING_DOCS"] = "true"  # docs loader
        os.environ["MILVUS_DROP_EXISTING"] = "true"  # code loader

    logger.info(
        "milvus=%s:%s embedding_model=%s",
        os.getenv("MILVUS_HOST", "localhost"),
        os.getenv("MILVUS_PORT", "19530"),
        os.getenv("EMBEDDING_MODEL", "BAAI/bge-base-en-v1.5"),
    )

    started = time.time()
    failed = 0
    if args.target in {"docs", "all"}:
        summary = ingest_docs(args.base_url, args.max_pages, args.crawl_delay, os.getenv("DOCS_COLLECTION", "docs_collection"))
        failed += summary.get("failed", 0)
    if args.target in {"code", "all"}:
        summary = ingest_code(args.repo, args.branch, os.getenv("CODE_COLLECTION", "code_collection"))
        failed += summary.get("failed", 0)

    logger.info("done in %.0fs", time.time() - started)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
