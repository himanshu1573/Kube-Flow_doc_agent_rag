"""
Docs Ingestion — KFP v2 Pipeline

Orchestrates the docs ingestion flow:
  crawl -> chunk -> embed -> load

Usage:
  python pipelines/docs_ingestion/pipeline.py
  python -m pipelines.docs_ingestion.pipeline --local
"""

import os
import sys

import kfp
from kfp import dsl
from kfp.dsl import Dataset, Input, Output


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


@dsl.component(
    base_image="python:3.11-slim",
    packages_to_install=["requests==2.32.3", "beautifulsoup4==4.12.3"],
)
def crawl_docs_site(
    base_url: str,
    crawl_delay: float,
    max_pages: int,
    crawled_pages: Output[Dataset],
):
    """Crawl Kubeflow docs and emit structured page JSONL."""
    import json
    import time
    from collections import deque
    from datetime import datetime, timezone
    from urllib.parse import urljoin, urlparse, urlunparse
    from xml.etree import ElementTree

    import requests
    from bs4 import BeautifulSoup

    MAIN_SELECTORS = (
        "main",
        "article",
        "#main-content",
        ".td-content",
        ".content",
        ".markdown-body",
    )
    CONTENT_TAGS = ("p", "li", "pre", "code", "table", "blockquote")
    HEADING_TAGS = ("h1", "h2", "h3")

    def normalize_url(url):
        parsed = urlparse(url)
        path = parsed.path.rstrip("/") or "/"
        clean = parsed._replace(path=path, query="", fragment="")
        return urlunparse(clean)

    def docs_root(url):
        return normalize_url(urljoin(url.rstrip("/") + "/", "docs/"))

    def is_docs_url(url, root):
        parsed = urlparse(normalize_url(url))
        base = urlparse(normalize_url(root))
        return parsed.netloc == base.netloc and (
            parsed.path == "/docs" or parsed.path.startswith("/docs/")
        )

    def extract_section(source_url):
        parts = [part for part in urlparse(source_url).path.split("/") if part]
        if not parts:
            return "root"
        if parts[0] != "docs":
            return parts[0]
        if len(parts) == 1:
            return "docs"
        return parts[1]

    def discover_urls(session, root):
        sitemap = urljoin(root.rstrip("/") + "/", "sitemap.xml")
        queue = deque([sitemap])
        seen_sitemaps = set()
        found = []

        while queue:
            current = normalize_url(queue.popleft())
            if current in seen_sitemaps:
                continue
            seen_sitemaps.add(current)
            try:
                response = session.get(current, timeout=30)
                response.raise_for_status()
                xml_root = ElementTree.fromstring(response.text)
            except Exception:
                continue

            root_name = xml_root.tag.rsplit("}", 1)[-1]
            for elem in xml_root.iter():
                if elem.tag.rsplit("}", 1)[-1] != "loc" or not elem.text:
                    continue
                location = normalize_url(elem.text.strip())
                if root_name == "sitemapindex":
                    if location not in seen_sitemaps:
                        queue.append(location)
                elif is_docs_url(location, root):
                    found.append(location)

        deduped = []
        seen_urls = set()
        for url in found:
            if url not in seen_urls:
                seen_urls.add(url)
                deduped.append(url)
        return deduped

    def fallback_discovery(session, root):
        start = docs_root(root)
        queue = deque([start])
        visited = set()
        discovered = []

        while queue:
            if max_pages and len(discovered) >= max_pages:
                break
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            try:
                response = session.get(current, timeout=30)
                response.raise_for_status()
            except Exception:
                continue

            discovered.append(current)
            soup = BeautifulSoup(response.text, "html.parser")
            for anchor in soup.select("a[href]"):
                href = anchor.get("href")
                if not href:
                    continue
                absolute = normalize_url(urljoin(current, href))
                if absolute not in visited and absolute not in queue and is_docs_url(absolute, root):
                    queue.append(absolute)

            if crawl_delay > 0:
                time.sleep(crawl_delay)

        return discovered

    def clean_content_tree(root):
        clone = BeautifulSoup(str(root), "html.parser")
        for selector in (
            "script",
            "style",
            "noscript",
            "header",
            "footer",
            "nav",
            ".breadcrumbs",
            ".toc",
            ".sidebar",
            ".page-meta",
            ".edit-page-link",
        ):
            for node in clone.select(selector):
                node.decompose()
        return clone

    def pick_main_content(soup):
        for selector in MAIN_SELECTORS:
            node = soup.select_one(selector)
            if node is not None:
                return node
        return soup.body

    def extract_page_title(soup, root):
        if root is not None:
            heading = root.find("h1")
            if heading and heading.get_text(strip=True):
                return heading.get_text(" ", strip=True)
        if soup.title and soup.title.get_text(strip=True):
            return soup.title.get_text(" ", strip=True)
        return "Untitled Kubeflow Docs Page"

    def extract_record(html, source_url):
        soup = BeautifulSoup(html, "html.parser")
        root = pick_main_content(soup)
        if root is None:
            return None

        cleaned = clean_content_tree(root)
        page_title = extract_page_title(soup, cleaned)
        sections = []
        current_heading = page_title
        current_lines = []

        def flush():
            nonlocal current_lines
            text = "\n".join(line.strip() for line in current_lines if line and line.strip()).strip()
            if text:
                sections.append({"heading": current_heading, "text": text})
            current_lines = []

        for node in cleaned.find_all(HEADING_TAGS + CONTENT_TAGS):
            text = node.get_text("\n" if node.name in {"pre", "code"} else " ", strip=True)
            if not text:
                continue
            if node.name in HEADING_TAGS:
                flush()
                current_heading = text
            else:
                current_lines.append(text)
        flush()

        if not sections:
            fallback = cleaned.get_text("\n", strip=True)
            if fallback:
                sections.append({"heading": page_title, "text": fallback})

        total_chars = sum(len(item["text"]) for item in sections)
        if total_chars < 120:
            return None

        return {
            "source_url": normalize_url(source_url),
            "page_title": page_title[:256],
            "section": extract_section(source_url)[:128],
            "crawled_at": datetime.now(timezone.utc).isoformat(),
            "sections": sections,
        }

    session = requests.Session()
    session.headers.update({"User-Agent": "kubeflow-docs-agent/phase1-crawler"})

    urls = discover_urls(session, base_url)
    if not urls:
        urls = fallback_discovery(session, base_url)

    if max_pages:
        urls = urls[:max_pages]

    pages = []
    for idx, url in enumerate(urls, start=1):
        try:
            response = session.get(url, timeout=30)
            response.raise_for_status()
        except Exception as exc:
            print(f"Failed to fetch {url}: {exc}")
            continue

        content_type = response.headers.get("Content-Type", "")
        if "html" not in content_type and "<html" not in response.text.lower():
            continue

        record = extract_record(response.text, url)
        if record:
            pages.append(record)

        if crawl_delay > 0:
            time.sleep(crawl_delay)

        if idx % 50 == 0:
            print(f"Crawled {idx}/{len(urls)} URLs ({len(pages)} valid pages)")

    print(f"Docs crawl complete: {len(pages)} pages")
    with open(crawled_pages.path, "w", encoding="utf-8") as handle:
        for page in pages:
            handle.write(json.dumps(page, ensure_ascii=False) + "\n")


@dsl.component(
    base_image="python:3.11-slim",
    packages_to_install=["langchain-text-splitters==0.3.0", "tiktoken==0.8.0"],
)
def chunk_docs(
    crawled_pages: Input[Dataset],
    chunk_size: int,
    chunk_overlap: int,
    chunked_data: Output[Dataset],
):
    """Chunk crawled docs pages into docs_collection-shaped records."""
    import hashlib
    import json

    import tiktoken
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    encoder = tiktoken.get_encoding("cl100k_base")
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    def count_tokens(text):
        return len(encoder.encode(text))

    pages = []
    with open(crawled_pages.path, "r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                pages.append(json.loads(line))

    chunks = []
    for page in pages:
        page_title = str(page.get("page_title", "Untitled"))[:256]
        section = str(page.get("section", "docs"))[:128]
        source_url = str(page.get("source_url", ""))[:512]
        crawled_at = str(page.get("crawled_at", ""))[:64]
        chunk_index = 0

        for section_data in page.get("sections", []):
            if not isinstance(section_data, dict):
                continue
            heading = str(section_data.get("heading") or page_title)[:256]
            text = str(section_data.get("text", "")).strip()
            if len(text) < 80:
                continue

            for split in splitter.split_text(text):
                split = split.strip()
                if len(split) < 80:
                    continue

                chunk_id = hashlib.sha256(
                    f"{source_url}::{heading}::{chunk_index}".encode()
                ).hexdigest()[:32]
                chunks.append(
                    {
                        "chunk_id": chunk_id,
                        "source_url": source_url,
                        "page_title": page_title,
                        "heading": heading,
                        "section": section,
                        "chunk_text": split[:16384],
                        "token_count": count_tokens(split),
                        "chunk_index": chunk_index,
                        "crawled_at": crawled_at,
                    }
                )
                chunk_index += 1

    print(f"Created {len(chunks)} docs chunks")
    with open(chunked_data.path, "w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(chunk, ensure_ascii=False) + "\n")


@dsl.component(
    base_image="python:3.11-slim",
    packages_to_install=["sentence-transformers==2.7.0", "torch==2.3.0"],
)
def embed_docs(
    chunked_data: Input[Dataset],
    embedding_model: str,
    embedded_data: Output[Dataset],
):
    """Embed docs chunks with contextual metadata."""
    import json

    from sentence_transformers import SentenceTransformer

    chunks = []
    with open(chunked_data.path, "r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                chunks.append(json.loads(line))

    model = SentenceTransformer(embedding_model)

    def build_text(chunk):
        parts = [
            f"# Title: {chunk.get('page_title', '')}",
            f"# Section: {chunk.get('section', '')}",
            f"# Heading: {chunk.get('heading', '')}",
            f"# URL: {chunk.get('source_url', '')}",
            "",
            str(chunk.get("chunk_text", "")),
        ]
        return "\n".join(parts).strip()

    texts = [build_text(chunk) for chunk in chunks]
    batch_size = 32
    embeddings = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        vectors = model.encode(batch, show_progress_bar=False)
        embeddings.extend([vector.tolist() for vector in vectors])

    for chunk, embedding in zip(chunks, embeddings):
        chunk["embedding"] = embedding

    with open(embedded_data.path, "w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(chunk, ensure_ascii=False) + "\n")


@dsl.component(
    base_image="python:3.11-slim",
    packages_to_install=["pymilvus==2.4.6"],
)
def load_docs(
    embedded_data: Input[Dataset],
    milvus_host: str,
    milvus_port: str,
    collection_name: str,
    embedding_dim: int,
):
    """Load embedded docs chunks into Milvus docs_collection."""
    import json
    import os

    from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility

    connections.connect("default", host=milvus_host, port=milvus_port)

    if os.environ.get("MILVUS_DROP_EXISTING_DOCS", "false").lower() == "true" and utility.has_collection(collection_name):
        utility.drop_collection(collection_name)

    if not utility.has_collection(collection_name):
        fields = [
            FieldSchema("chunk_id", DataType.VARCHAR, max_length=128, is_primary=True),
            FieldSchema("source_url", DataType.VARCHAR, max_length=512),
            FieldSchema("page_title", DataType.VARCHAR, max_length=256),
            FieldSchema("heading", DataType.VARCHAR, max_length=256),
            FieldSchema("section", DataType.VARCHAR, max_length=128),
            FieldSchema("chunk_text", DataType.VARCHAR, max_length=16384),
            FieldSchema("token_count", DataType.INT64),
            FieldSchema("chunk_index", DataType.INT64),
            FieldSchema("crawled_at", DataType.VARCHAR, max_length=64),
            FieldSchema("embedding", DataType.FLOAT_VECTOR, dim=embedding_dim),
        ]
        schema = CollectionSchema(fields, "Kubeflow docs chunks for RAG retrieval")
        collection = Collection(collection_name, schema)
        collection.create_index(
            "embedding",
            {
                "metric_type": "COSINE",
                "index_type": "HNSW",
                "params": {"M": 16, "efConstruction": 200},
            },
        )
    else:
        collection = Collection(collection_name)

    collection.load()

    rows = []
    with open(embedded_data.path, "r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            chunk = json.loads(line)
            if "embedding" not in chunk:
                continue
            rows.append(
                {
                    "chunk_id": str(chunk["chunk_id"])[:128],
                    "source_url": str(chunk.get("source_url", ""))[:512],
                    "page_title": str(chunk.get("page_title", ""))[:256],
                    "heading": str(chunk.get("heading", ""))[:256],
                    "section": str(chunk.get("section", ""))[:128],
                    "chunk_text": str(chunk.get("chunk_text", ""))[:16384],
                    "token_count": int(chunk.get("token_count", 0)),
                    "chunk_index": int(chunk.get("chunk_index", 0)),
                    "crawled_at": str(chunk.get("crawled_at", ""))[:64],
                    "embedding": chunk["embedding"],
                }
            )

    batch_size = 100
    inserted = 0
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        collection.upsert(batch)
        inserted += len(batch)

    collection.flush()
    print(f"Loaded {inserted} docs chunks into {collection_name}")


@dsl.pipeline(
    name="docs-ingestion-pipeline",
    description="Crawl Kubeflow docs, chunk, embed, and load into Milvus",
)
def docs_ingestion_pipeline(
    base_url: str = "https://www.kubeflow.org",
    crawl_delay: float = 0.0,
    max_pages: int = 0,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
    embedding_model: str = "BAAI/bge-base-en-v1.5",
    milvus_host: str = "localhost",
    milvus_port: str = "19530",
    collection_name: str = "docs_collection",
    embedding_dim: int = 384,
):
    crawl_task = crawl_docs_site(
        base_url=base_url,
        crawl_delay=crawl_delay,
        max_pages=max_pages,
    )
    crawl_task.set_retry(num_retries=3, backoff_duration="30s", backoff_factor=2.0)

    chunk_task = chunk_docs(
        crawled_pages=crawl_task.outputs["crawled_pages"],
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    chunk_task.set_retry(num_retries=3, backoff_duration="30s", backoff_factor=2.0)

    embed_task = embed_docs(
        chunked_data=chunk_task.outputs["chunked_data"],
        embedding_model=embedding_model,
    )
    embed_task.set_retry(num_retries=3, backoff_duration="30s", backoff_factor=2.0)

    load_task = load_docs(
        embedded_data=embed_task.outputs["embedded_data"],
        milvus_host=milvus_host,
        milvus_port=milvus_port,
        collection_name=collection_name,
        embedding_dim=embedding_dim,
    )
    load_task.set_retry(num_retries=3, backoff_duration="30s", backoff_factor=2.0)


if __name__ == "__main__":
    if "--local" in sys.argv:
        from pipelines.docs_ingestion.components.chunker import chunk_pages
        from pipelines.docs_ingestion.components.crawler import crawl_docs
        from pipelines.docs_ingestion.components.embedder import embed_docs_chunks
        from pipelines.docs_ingestion.components.loader import load_to_milvus

        pages = crawl_docs(max_pages=0)
        chunks = chunk_pages(pages)
        embedded = embed_docs_chunks(chunks)
        summary = load_to_milvus(embedded)
        print(f"Docs ingestion complete: {summary}")
    else:
        output_path = os.path.join(os.path.dirname(__file__), "pipeline.yaml")
        kfp.compiler.Compiler().compile(
            pipeline_func=docs_ingestion_pipeline,
            package_path=output_path,
        )
        print(f"Compiled docs ingestion pipeline to: {output_path}")
