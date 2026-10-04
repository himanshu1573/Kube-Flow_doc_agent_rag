"""
Docs Ingestion — Chunker Component

Splits crawled Kubeflow docs pages into structure-aware chunks while preserving:
  - page and URL breadcrumb context
  - heading hierarchy
  - command/code blocks
  - procedural step groups
  - chunk types for better reranking
"""

import hashlib
import json
import logging
import os
import re
from typing import Dict, Iterable, List, Sequence, Tuple

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:
    class RecursiveCharacterTextSplitter:  # type: ignore[override]
        """Lightweight fallback splitter for local development."""

        def __init__(self, chunk_size: int, chunk_overlap: int, length_function, separators):
            self.chunk_size = chunk_size
            self.chunk_overlap = chunk_overlap
            self.length_function = length_function

        def split_text(self, text: str) -> List[str]:
            if self.length_function(text) <= self.chunk_size:
                return [text]

            chunks: List[str] = []
            start = 0
            text_length = len(text)
            while start < text_length:
                end = min(text_length, start + self.chunk_size)
                chunk = text[start:end].strip()
                if chunk:
                    chunks.append(chunk)
                if end >= text_length:
                    break
                start = max(end - self.chunk_overlap, start + 1)
            return chunks

logger = logging.getLogger(__name__)

try:
    import tiktoken

    _ENCODER = None

    def _get_encoder():
        global _ENCODER
        if _ENCODER is None:
            try:
                _ENCODER = tiktoken.get_encoding("cl100k_base")
            except Exception:
                _ENCODER = False
        return _ENCODER

    def count_tokens(text: str) -> int:
        encoder = _get_encoder()
        if encoder is False:
            return max(1, int(len(text.split()) * 1.3))
        return len(encoder.encode(text))

except ImportError:
    def count_tokens(text: str) -> int:
        return max(1, int(len(text.split()) * 1.3))


COMMAND_PATTERN = re.compile(
    r"\b(kubectl|kustomize|helm|curl|wget|pip|python|make|docker|gcloud|export|cat)\b"
    r"|(^|\n)\s*(apiVersion:|kind:|metadata:)",
    re.IGNORECASE,
)
FAQ_HEADING_PATTERN = re.compile(r"^(what|how|why|when|where|can|does|is)\b", re.IGNORECASE)
PROCEDURE_PATTERN = re.compile(
    r"\b(step|install|installation|setup|configure|run|deploy|create|apply|first|next|then)\b",
    re.IGNORECASE,
)


def build_chunk_id(source_url: str, heading_path: str, chunk_type: str, chunk_index: int) -> str:
    raw = f"{source_url}::{heading_path}::{chunk_type}::{chunk_index}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def get_splitter(chunk_size: int, chunk_overlap: int) -> RecursiveCharacterTextSplitter:
    """Create a token-aware text splitter."""
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=count_tokens,
        separators=["\n\n", "\n", ". ", " ", ""],
    )


def normalize_text(value: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", value.strip())


def classify_chunk_type(
    heading: str,
    text: str,
    block_type: str = "paragraph",
) -> str:
    """Classify a chunk into retrieval-friendly types."""
    heading_lower = heading.strip().lower()
    text_lower = text.strip().lower()

    if block_type == "code" or COMMAND_PATTERN.search(text):
        return "command"
    if block_type == "list_step":
        return "procedure"
    if heading.endswith("?") or FAQ_HEADING_PATTERN.match(heading_lower):
        return "faq"
    if PROCEDURE_PATTERN.search(heading_lower) or PROCEDURE_PATTERN.search(text_lower):
        return "procedure"
    return "concept"


def block_chunk_plan(chunk_type: str) -> Tuple[int, int]:
    """Choose chunk sizing based on content type."""
    if chunk_type == "command":
        return 320, 40
    if chunk_type == "procedure":
        return 900, 120
    if chunk_type == "faq":
        return 700, 80
    return 680, 80


def join_step_blocks(blocks: Sequence[Dict[str, str]]) -> List[str]:
    """Aggregate ordered-list steps into retrieval-friendly procedure snippets."""
    grouped: List[str] = []
    current: List[str] = []

    for block in blocks:
        if block.get("type") == "list_step":
            current.append(block.get("text", "").strip())
            continue
        if current:
            grouped.append("\n".join(f"Step {index + 1}: {value}" for index, value in enumerate(current)))
            current = []

    if current:
        grouped.append("\n".join(f"Step {index + 1}: {value}" for index, value in enumerate(current)))

    return grouped


def build_context_prefix(
    page_title: str,
    section: str,
    breadcrumb_path: str,
    heading_path: str,
    parent_heading: str,
    chunk_type: str,
    source_url: str,
) -> str:
    lines = [
        f"# Title: {page_title}",
        f"# Section: {section}",
        f"# Breadcrumb: {breadcrumb_path}",
        f"# Heading Path: {heading_path}",
        f"# Parent Heading: {parent_heading}",
        f"# Chunk Type: {chunk_type}",
        f"# URL: {source_url}",
    ]
    return "\n".join(lines)


def split_with_context(
    text: str,
    chunk_type: str,
    context_prefix: str,
) -> List[str]:
    """Split content using type-aware chunk sizes while preserving context headers."""
    chunk_size, chunk_overlap = block_chunk_plan(chunk_type)
    splitter = get_splitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    return [
        normalize_text(f"{context_prefix}\n\n{chunk}")
        for chunk in splitter.split_text(text)
        if normalize_text(chunk)
    ]


def chunk_pages(
    pages: Iterable[Dict[str, object]],
    chunk_size: int = 680,
    chunk_overlap: int = 80,
) -> List[Dict[str, object]]:
    """Split crawled page sections into structure-aware docs chunk records."""
    del chunk_size, chunk_overlap  # Type-aware split sizing is used internally.

    records: List[Dict[str, object]] = []

    for page in pages:
        source_url = str(page.get("source_url", ""))
        page_title = str(page.get("page_title", "Untitled"))[:256]
        section = str(page.get("section", "docs"))[:128]
        breadcrumb_path = str(page.get("breadcrumb_path", section.title() or "Docs"))[:256]
        crawled_at = str(page.get("crawled_at", ""))
        chunk_index = 0
        seen_payloads = set()

        for section_data in page.get("sections", []):
            if not isinstance(section_data, dict):
                continue

            heading = str(section_data.get("heading") or page_title)[:256]
            parent_heading = str(section_data.get("parent_heading") or page_title)[:256]
            heading_path = str(section_data.get("heading_path") or heading)[:512]
            text = normalize_text(str(section_data.get("text", "")))
            if len(text) < 80:
                continue

            blocks = section_data.get("blocks", [])
            if not isinstance(blocks, list):
                blocks = []

            main_chunk_type = classify_chunk_type(heading, text)
            main_prefix = build_context_prefix(
                page_title=page_title,
                section=section,
                breadcrumb_path=breadcrumb_path,
                heading_path=heading_path,
                parent_heading=parent_heading,
                chunk_type=main_chunk_type,
                source_url=source_url,
            )

            for split in split_with_context(text, main_chunk_type, main_prefix):
                payload_key = (heading_path, main_chunk_type, split)
                if payload_key in seen_payloads or count_tokens(split) < 40:
                    continue
                seen_payloads.add(payload_key)
                records.append(
                    {
                        "chunk_id": build_chunk_id(source_url, heading_path, main_chunk_type, chunk_index),
                        "source_url": source_url[:512],
                        "page_title": page_title,
                        "heading": heading,
                        "parent_heading": parent_heading,
                        "heading_path": heading_path,
                        "breadcrumb_path": breadcrumb_path,
                        "section": section,
                        "chunk_type": main_chunk_type,
                        "chunk_text": split[:16384],
                        "token_count": count_tokens(split),
                        "chunk_index": chunk_index,
                        "crawled_at": crawled_at[:64],
                    }
                )
                chunk_index += 1

            step_groups = join_step_blocks(blocks)
            for step_group in step_groups:
                chunk_type = "procedure"
                prefix = build_context_prefix(
                    page_title=page_title,
                    section=section,
                    breadcrumb_path=breadcrumb_path,
                    heading_path=heading_path,
                    parent_heading=parent_heading,
                    chunk_type=chunk_type,
                    source_url=source_url,
                )
                for split in split_with_context(step_group, chunk_type, prefix):
                    payload_key = (heading_path, chunk_type, split)
                    if payload_key in seen_payloads or count_tokens(split) < 30:
                        continue
                    seen_payloads.add(payload_key)
                    records.append(
                        {
                            "chunk_id": build_chunk_id(source_url, heading_path, chunk_type, chunk_index),
                            "source_url": source_url[:512],
                            "page_title": page_title,
                            "heading": heading,
                            "parent_heading": parent_heading,
                            "heading_path": heading_path,
                            "breadcrumb_path": breadcrumb_path,
                            "section": section,
                            "chunk_type": chunk_type,
                            "chunk_text": split[:16384],
                            "token_count": count_tokens(split),
                            "chunk_index": chunk_index,
                            "crawled_at": crawled_at[:64],
                        }
                    )
                    chunk_index += 1

            for block in blocks:
                if not isinstance(block, dict):
                    continue
                block_text = normalize_text(str(block.get("text", "")))
                if len(block_text) < 20:
                    continue
                block_type = str(block.get("type", "paragraph"))
                chunk_type = classify_chunk_type(heading, block_text, block_type=block_type)
                if chunk_type not in {"command", "faq"}:
                    continue

                prefix = build_context_prefix(
                    page_title=page_title,
                    section=section,
                    breadcrumb_path=breadcrumb_path,
                    heading_path=heading_path,
                    parent_heading=parent_heading,
                    chunk_type=chunk_type,
                    source_url=source_url,
                )

                for split in split_with_context(block_text, chunk_type, prefix):
                    payload_key = (heading_path, chunk_type, split)
                    if payload_key in seen_payloads or count_tokens(split) < 20:
                        continue
                    seen_payloads.add(payload_key)
                    records.append(
                        {
                            "chunk_id": build_chunk_id(source_url, heading_path, chunk_type, chunk_index),
                            "source_url": source_url[:512],
                            "page_title": page_title,
                            "heading": heading,
                            "parent_heading": parent_heading,
                            "heading_path": heading_path,
                            "breadcrumb_path": breadcrumb_path,
                            "section": section,
                            "chunk_type": chunk_type,
                            "chunk_text": split[:16384],
                            "token_count": count_tokens(split),
                            "chunk_index": chunk_index,
                            "crawled_at": crawled_at[:64],
                        }
                    )
                    chunk_index += 1

    logger.info("Docs chunker: produced %d chunks", len(records))
    return records


def save_chunks(chunks: Iterable[Dict[str, object]], output_path: str) -> None:
    """Save chunk records to JSONL."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(chunk, ensure_ascii=False) + "\n")
    logger.info("Saved docs chunks to %s", output_path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    sample_pages = [
        {
            "source_url": "https://www.kubeflow.org/docs/components/pipelines/",
            "page_title": "Kubeflow Pipelines",
            "section": "components",
            "breadcrumb_path": "Docs > Components > Pipelines",
            "crawled_at": "2026-04-09T00:00:00Z",
            "sections": [
                {
                    "heading": "Install Kubeflow Pipelines",
                    "parent_heading": "Kubeflow Pipelines",
                    "heading_path": "Kubeflow Pipelines > Install Kubeflow Pipelines",
                    "text": (
                        "Follow these steps to install Kubeflow Pipelines. "
                        "Run kubectl apply on the manifests and verify the deployment. "
                    ) * 10,
                    "blocks": [
                        {"type": "paragraph", "text": "Follow these steps to install Kubeflow Pipelines."},
                        {"type": "list_step", "text": "Create the namespace."},
                        {"type": "list_step", "text": "Apply the manifests."},
                        {"type": "code", "text": "kubectl apply -k manifests/"},
                    ],
                }
            ],
        }
    ]
    chunks = chunk_pages(sample_pages)
    logger.info("Generated %d chunks", len(chunks))
