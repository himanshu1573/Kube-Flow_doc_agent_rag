"""Shared Milvus-backed retrieval layer for Phase 2 runtime paths."""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, Iterable, List, Literal, Tuple

from agent.core.router import RouteDecision, classify_question
from pipelines.shared.embedding_utils import prepare_embedding_texts
from pipelines.shared.retrieval_strategy import rerank_hits

TargetMode = Literal["auto", "docs", "code"]

MILVUS_HOST = os.getenv("MILVUS_HOST", "localhost")
MILVUS_PORT = os.getenv("MILVUS_PORT", "19530")
MILVUS_TOKEN = os.getenv("MILVUS_TOKEN", "")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-base-en-v1.5")

DOCS_COLLECTION = os.getenv("DOCS_COLLECTION", "docs_collection")
LEGACY_DOCS_COLLECTION = os.getenv("LEGACY_DOCS_COLLECTION", "docs_rag")
CODE_COLLECTION = os.getenv("CODE_COLLECTION", "code_collection")
CODE_BASE_URL = os.getenv(
    "KUBEFLOW_CODE_BASE_URL",
    "https://github.com/kubeflow/manifests/blob/master",
)

_ENCODER: Any | None = None
_ENCODER_LOCK = threading.Lock()


def get_encoder() -> Any:
    """Lazy-load the embedding model once per process."""
    global _ENCODER
    if _ENCODER is None:
        with _ENCODER_LOCK:
            if _ENCODER is None:
                from sentence_transformers import SentenceTransformer

                _ENCODER = SentenceTransformer(EMBEDDING_MODEL)
    return _ENCODER


def ensure_connection() -> None:
    """Ensure Milvus connection exists."""
    from pymilvus import connections

    params: Dict[str, Any] = {
        "alias": "default",
        "host": MILVUS_HOST,
        "port": MILVUS_PORT,
    }
    if MILVUS_TOKEN:
        params["token"] = MILVUS_TOKEN
    try:
        connections.connect(**params)
    except Exception:
        # Retry once in case the alias already exists in an odd state.
        try:
            connections.disconnect(alias="default")
        except Exception:
            pass
        connections.connect(**params)


def resolve_docs_collection() -> str:
    """Prefer the new docs collection but fall back to the legacy one if needed."""
    from pymilvus import utility

    ensure_connection()
    if utility.has_collection(DOCS_COLLECTION):
        return DOCS_COLLECTION
    if utility.has_collection(LEGACY_DOCS_COLLECTION):
        return LEGACY_DOCS_COLLECTION
    return DOCS_COLLECTION


def resolve_code_collection() -> str:
    """Return the configured code collection."""
    ensure_connection()
    return CODE_COLLECTION


def build_code_citation_url(file_path: str, start_line: int | None = None) -> str:
    """Build a GitHub citation URL for a code hit."""
    base = CODE_BASE_URL.rstrip("/")
    if not file_path:
        return base
    anchor = f"#L{start_line}" if start_line and start_line > 0 else ""
    return f"{base}/{file_path}{anchor}"


def _collection_field_names(collection: Any) -> set[str]:
    return {field.name for field in collection.schema.fields}


def _search_collection(
    collection_name: str,
    query: str,
    output_candidates: Iterable[str],
    top_k: int,
) -> Tuple[str, List[Dict[str, Any]]]:
    from pymilvus import Collection

    ensure_connection()
    collection = Collection(collection_name)
    collection.load()

    field_names = _collection_field_names(collection)
    output_fields = [field for field in output_candidates if field in field_names]
    prepared_query = prepare_embedding_texts(
        [query],
        model_name=EMBEDDING_MODEL,
        purpose="query",
    )[0]
    query_vec = get_encoder().encode(
        prepared_query,
        normalize_embeddings=True,
    ).tolist()

    results = None
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            results = collection.search(
                data=[query_vec],
                anns_field="embedding" if "embedding" in field_names else "vector",
                param={"metric_type": "COSINE", "params": {"ef": 64}},
                limit=int(top_k),
                output_fields=output_fields,
            )
            break
        except Exception as exc:
            last_error = exc
            time.sleep(0.4 * (2**attempt))

    if results is None:
        raise RuntimeError(
            f"Milvus search failed for collection '{collection_name}': {last_error}"
        )

    hits: List[Dict[str, Any]] = []
    for hit in results[0]:
        entity = hit.entity
        item = {"distance": float(hit.distance), "collection": collection_name}
        for field in output_fields:
            item[field] = entity.get(field)
        hits.append(item)
    return collection_name, hits


def search_docs(query: str, top_k: int = 5) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Search the docs collection."""
    collection_name = resolve_docs_collection()
    _, hits = _search_collection(
        collection_name,
        query,
        output_candidates=[
            "source_url",
            "page_title",
            "heading",
            "parent_heading",
            "heading_path",
            "breadcrumb_path",
            "section",
            "chunk_type",
            "chunk_text",
            "token_count",
            "file_path",
            "citation_url",
            "content_text",
        ],
        top_k=top_k,
    )

    citations: List[str] = []
    normalized: List[Dict[str, Any]] = []
    for hit in hits:
        citation = hit.get("source_url") or hit.get("citation_url") or ""
        if citation and citation not in citations:
            citations.append(str(citation))
        normalized.append(
            {
                "collection": "docs_collection",
                "distance": hit.get("distance", 0.0),
                "source_url": citation,
                "page_title": hit.get("page_title") or "Kubeflow Docs",
                "heading": hit.get("heading") or "",
                "parent_heading": hit.get("parent_heading") or "",
                "heading_path": hit.get("heading_path") or hit.get("heading") or "",
                "breadcrumb_path": hit.get("breadcrumb_path") or "",
                "section": hit.get("section") or "",
                "chunk_type": hit.get("chunk_type") or "concept",
                "chunk_text": hit.get("chunk_text") or hit.get("content_text") or "",
            }
        )
    return normalized, citations


def search_code(query: str, top_k: int = 5) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Search the code collection."""
    collection_name = resolve_code_collection()
    _, hits = _search_collection(
        collection_name,
        query,
        output_candidates=[
            "file_path",
            "extension",
            "language",
            "chunk_type",
            "symbol_name",
            "folder_context",
            "chunk_text",
            "start_line",
            "end_line",
            "commit_sha",
            "chunk_index",
        ],
        top_k=top_k,
    )

    citations: List[str] = []
    normalized: List[Dict[str, Any]] = []
    for hit in hits:
        citation = build_code_citation_url(
            str(hit.get("file_path", "")),
            int(hit.get("start_line", 0) or 0),
        )
        if citation and citation not in citations:
            citations.append(citation)
        normalized.append(
            {
                "collection": "code_collection",
                "distance": hit.get("distance", 0.0),
                "file_path": hit.get("file_path") or "",
                "language": hit.get("language") or "",
                "chunk_type": hit.get("chunk_type") or "symbol",
                "symbol_name": hit.get("symbol_name") or "",
                "start_line": hit.get("start_line") or 0,
                "end_line": hit.get("end_line") or 0,
                "source_url": citation,
                "chunk_text": hit.get("chunk_text") or "",
            }
        )
    return normalized, citations


def format_hits(hits: List[Dict[str, Any]]) -> Tuple[str, List[str]]:
    """Format normalized hits for LLM tool consumption."""
    citations: List[str] = []
    lines: List[str] = []

    for hit in hits:
        citation = str(hit.get("source_url") or "")
        if citation and citation not in citations:
            citations.append(citation)

        if hit.get("collection") == "code_collection":
            lines.append(
                "\n".join(
                    [
                        "[CODE]",
                        f"File: {hit.get('file_path', '')}",
                        f"Chunk Type: {hit.get('chunk_type', '')}",
                        f"Symbol: {hit.get('symbol_name', '')}",
                        f"Language: {hit.get('language', '')}",
                        f"Lines: {hit.get('start_line', 0)}-{hit.get('end_line', 0)}",
                        f"URL: {citation}",
                        f"Snippet: {str(hit.get('chunk_text', ''))[:600]}",
                        f"Score: {hit.get('rerank_score', hit.get('distance', 0.0)):.3f}",
                    ]
                )
            )
        else:
            lines.append(
                "\n".join(
                    [
                        "[DOCS]",
                        f"Title: {hit.get('page_title', 'Kubeflow Docs')}",
                        f"Heading: {hit.get('heading', '')}",
                        f"Heading Path: {hit.get('heading_path', '')}",
                        f"Chunk Type: {hit.get('chunk_type', '')}",
                        f"Section: {hit.get('section', '')}",
                        f"URL: {citation}",
                        f"Snippet: {str(hit.get('chunk_text', ''))[:600]}",
                        f"Score: {hit.get('rerank_score', hit.get('distance', 0.0)):.3f}",
                    ]
                )
            )

    return ("\n\n".join(lines) if lines else "No relevant results found."), citations


def search_context(
    query: str,
    top_k: int = 5,
    target: TargetMode = "auto",
) -> Tuple[str, List[str], RouteDecision]:
    """Search docs, code, or both with server-side routing and reranking."""
    route = classify_question(query)
    search_query = str(route.query_analysis.get("enhanced_query", query))
    candidate_limit = max(top_k * 4, 12)

    if target == "docs":
        docs_hits, docs_citations = search_docs(search_query, top_k=candidate_limit)
        reranked = rerank_hits(docs_hits, route.query_analysis, top_k)
        formatted, citations = format_hits(reranked)
        return formatted, (citations or docs_citations), route

    if target == "code":
        code_hits, code_citations = search_code(search_query, top_k=candidate_limit)
        reranked = rerank_hits(code_hits, route.query_analysis, top_k)
        formatted, citations = format_hits(reranked)
        return formatted, (citations or code_citations), route

    candidate_hits: List[Dict[str, Any]] = []
    candidate_citations: List[str] = []

    if route.target in {"docs", "hybrid"}:
        docs_hits, docs_citations = search_docs(search_query, top_k=candidate_limit)
        candidate_hits.extend(docs_hits)
        candidate_citations.extend(docs_citations)

    if route.target in {"code", "hybrid"}:
        code_hits, code_citations = search_code(search_query, top_k=candidate_limit)
        candidate_hits.extend(code_hits)
        candidate_citations.extend(code_citations)

    reranked = rerank_hits(candidate_hits, route.query_analysis, top_k)
    formatted, citations = format_hits(reranked)

    merged_citations = citations[:]
    for citation in candidate_citations:
        if citation not in merged_citations:
            merged_citations.append(citation)

    return formatted, merged_citations, route


def build_tools_for_route(route_target: Literal["docs", "code", "hybrid"]) -> List[Dict[str, Any]]:
    """Build the tool list exposed to the LLM for a given route."""
    tools: List[Dict[str, Any]] = [
        {
            "type": "function",
            "function": {
                "name": "search_kubeflow_context",
                "description": (
                    "Search Kubeflow docs, manifests, or both. "
                    "Use this tool first for most Kubeflow-specific questions."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "minLength": 1},
                        "top_k": {"type": "integer", "default": 5, "minimum": 1, "maximum": 10},
                        "target": {
                            "type": "string",
                            "enum": ["auto", "docs", "code"],
                            "default": "auto",
                        },
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
        }
    ]

    if route_target in {"docs", "hybrid"}:
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "search_kubeflow_docs",
                    "description": "Search the official Kubeflow docs collection.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "minLength": 1},
                            "top_k": {"type": "integer", "default": 5, "minimum": 1, "maximum": 10},
                        },
                        "required": ["query"],
                        "additionalProperties": False,
                    },
                },
            }
        )

    if route_target in {"code", "hybrid"}:
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "search_kubeflow_code",
                    "description": (
                        "Search Kubeflow manifests/code for YAML, RBAC, Helm, "
                        "Kustomize, webhooks, and implementation details."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "minLength": 1},
                            "top_k": {"type": "integer", "default": 5, "minimum": 1, "maximum": 10},
                        },
                        "required": ["query"],
                        "additionalProperties": False,
                    },
                },
            }
        )

    return tools


def execute_tool_call(tool_call: Dict[str, Any]) -> Tuple[str, List[str]]:
    """Execute any supported Phase 2 retrieval tool call."""
    function_name = tool_call.get("function", {}).get("name")
    arguments = json.loads(tool_call.get("function", {}).get("arguments", "{}"))
    query = arguments.get("query", "")
    top_k = int(arguments.get("top_k", 5))

    if function_name == "search_kubeflow_docs":
        hits, citations = search_docs(query, top_k=top_k)
        return format_hits(hits)[0], citations

    if function_name == "search_kubeflow_code":
        hits, citations = search_code(query, top_k=top_k)
        return format_hits(hits)[0], citations

    if function_name == "search_kubeflow_context":
        target = arguments.get("target", "auto")
        formatted, citations, _ = search_context(query, top_k=top_k, target=target)
        return formatted, citations

    return f"Unknown tool: {function_name}", []
