"""
Docs Ingestion — Crawler Component

Crawls official Kubeflow documentation pages from kubeflow.org and extracts
structured page records for downstream chunking and embedding.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Set
from urllib.parse import urljoin, urlparse, urlunparse
from xml.etree import ElementTree

try:
    import requests
except ImportError:  # pragma: no cover - dependency availability varies by env
    requests = None

try:
    from bs4 import BeautifulSoup, Tag
except ImportError:  # pragma: no cover - dependency availability varies by env
    BeautifulSoup = None
    Tag = Any

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = "kubeflow-docs-agent/phase1-crawler"
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


def normalize_url(url: str) -> str:
    """Normalize a URL for deduplication."""
    parsed = urlparse(url)
    normalized_path = parsed.path.rstrip("/") or "/"
    clean = parsed._replace(fragment="", query="", path=normalized_path)
    return urlunparse(clean)


def get_docs_root(base_url: str) -> str:
    """Return the canonical docs root for a Kubeflow website URL."""
    return normalize_url(urljoin(base_url.rstrip("/") + "/", "docs/"))


def is_docs_url(url: str, base_url: str) -> bool:
    """Check if a URL belongs to the Kubeflow docs area."""
    parsed = urlparse(normalize_url(url))
    base = urlparse(normalize_url(base_url))
    
    # Lenient netloc check: allow kubeflow.org and www.kubeflow.org
    p_net = parsed.netloc.replace("www.", "")
    b_net = base.netloc.replace("www.", "")
    
    if p_net != b_net:
        return False
    return parsed.path == "/docs" or parsed.path.startswith("/docs/")


def extract_section_from_url(source_url: str) -> str:
    """Infer the top-level docs section from the page URL."""
    path_parts = [part for part in urlparse(source_url).path.split("/") if part]
    if not path_parts:
        return "root"
    if path_parts[0] != "docs":
        return path_parts[0]
    if len(path_parts) == 1:
        return "docs"
    return path_parts[1]


def build_breadcrumb_path(source_url: str) -> str:
    """Build a lightweight breadcrumb trail from the URL path."""
    path_parts = [part for part in urlparse(source_url).path.split("/") if part]
    breadcrumb_parts: List[str] = []
    for part in path_parts:
        normalized = part.replace("-", " ").replace("_", " ").strip()
        if not normalized:
            continue
        breadcrumb_parts.append(normalized.title())
    return " > ".join(breadcrumb_parts) if breadcrumb_parts else "Docs"


def discover_sitemap_urls(
    session: requests.Session,
    base_url: str,
    max_urls: int = 10000,
) -> List[str]:
    """Discover docs URLs from sitemap.xml, following sitemap indexes recursively."""
    sitemap_url = urljoin(base_url.rstrip("/") + "/", "sitemap.xml")
    queue = deque([sitemap_url])
    seen_sitemaps: Set[str] = set()
    urls: List[str] = []

    while queue and len(urls) < max_urls:
        current = queue.popleft()
        current = normalize_url(current)
        if current in seen_sitemaps:
            continue
        seen_sitemaps.add(current)

        try:
            response = session.get(current, timeout=30)
            response.raise_for_status()
            root = ElementTree.fromstring(response.text)
        except Exception as exc:
            logger.warning("Could not parse sitemap %s: %s", current, exc)
            continue

        tag_name = root.tag.rsplit("}", 1)[-1]
        for elem in root.iter():
            elem_name = elem.tag.rsplit("}", 1)[-1]
            if elem_name != "loc" or not elem.text:
                continue

            location = normalize_url(elem.text.strip())
            if tag_name == "sitemapindex":
                if location not in seen_sitemaps:
                    queue.append(location)
            elif is_docs_url(location, base_url):
                urls.append(location)

    deduped: List[str] = []
    seen_urls: Set[str] = set()
    for url in urls:
        if url not in seen_urls:
            seen_urls.add(url)
            deduped.append(url)
    return deduped


def discover_docs_links(
    session: requests.Session,
    base_url: str,
    crawl_delay: float,
    max_pages: int,
) -> List[str]:
    """Fallback discovery using a constrained BFS from /docs/."""
    docs_root = get_docs_root(base_url)
    queue = deque([docs_root])
    visited: Set[str] = set()
    discovered: List[str] = []

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
        except Exception as exc:
            logger.warning("Failed to fetch %s during discovery: %s", current, exc)
            continue

        discovered.append(current)
        soup = BeautifulSoup(response.text, "html.parser")
        for anchor in soup.select("a[href]"):
            href = anchor.get("href")
            if not href:
                continue
            absolute = normalize_url(urljoin(current, href))
            if absolute in visited or absolute in queue:
                continue
            if is_docs_url(absolute, base_url):
                queue.append(absolute)

        if crawl_delay > 0:
            time.sleep(crawl_delay)

    return discovered


def _pick_main_content(soup: BeautifulSoup) -> Optional[Tag]:
    for selector in MAIN_SELECTORS:
        node = soup.select_one(selector)
        if node is not None:
            return node
    return soup.body


def _clean_content_tree(root: Tag) -> Tag:
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


def _extract_page_title(soup: BeautifulSoup, content_root: Optional[Tag]) -> str:
    if content_root is not None:
        heading = content_root.find("h1")
        if heading and heading.get_text(strip=True):
            return heading.get_text(" ", strip=True)
    if soup.title and soup.title.get_text(strip=True):
        return soup.title.get_text(" ", strip=True)
    return "Untitled Kubeflow Docs Page"


def extract_sections_from_html(html: str, source_url: str) -> Dict[str, object]:
    """Extract a structured page record from HTML."""
    if BeautifulSoup is None:
        raise RuntimeError("beautifulsoup4 is required for docs crawling")
    soup = BeautifulSoup(html, "html.parser")
    root = _pick_main_content(soup)
    if root is None:
        return {}

    cleaned = _clean_content_tree(root)
    page_title = _extract_page_title(soup, cleaned)
    section = extract_section_from_url(source_url)
    crawled_at = datetime.now(timezone.utc).isoformat()

    breadcrumb_path = build_breadcrumb_path(source_url)
    sections: List[Dict[str, object]] = []
    current_heading = page_title
    current_parent_heading = page_title
    current_heading_path = page_title
    heading_stack: Dict[int, str] = {1: page_title}
    current_blocks: List[Dict[str, str]] = []

    def classify_block(node: Tag) -> str:
        if node.name in {"pre", "code"}:
            return "code"
        if node.name == "li":
            return "list_step" if node.parent and node.parent.name == "ol" else "list_item"
        if node.name == "blockquote":
            return "note"
        if node.name == "table":
            return "reference"
        return "paragraph"

    def flush_section() -> None:
        nonlocal current_blocks
        text_parts = [block["text"] for block in current_blocks if block.get("text")]
        text = "\n\n".join(text_parts).strip()
        if text:
            sections.append(
                {
                    "heading": current_heading,
                    "parent_heading": current_parent_heading,
                    "heading_path": current_heading_path,
                    "blocks": list(current_blocks),
                    "text": text,
                }
            )
        current_blocks = []

    for node in cleaned.find_all(HEADING_TAGS + CONTENT_TAGS):
        text = node.get_text("\n" if node.name in {"pre", "code"} else " ", strip=True)
        if not text:
            continue

        if node.name in HEADING_TAGS:
            flush_section()
            level = int(node.name[1])
            heading_stack[level] = text
            for depth in list(heading_stack):
                if depth > level:
                    heading_stack.pop(depth, None)

            current_heading = text
            current_parent_heading = heading_stack.get(level - 1, page_title)
            current_heading_path = " > ".join(
                heading_stack[depth] for depth in sorted(heading_stack)
            )
        else:
            current_blocks.append({"type": classify_block(node), "text": text})

    flush_section()

    if not sections:
        fallback_text = cleaned.get_text("\n", strip=True)
        if fallback_text:
            sections.append(
                {
                    "heading": page_title,
                    "parent_heading": page_title,
                    "heading_path": page_title,
                    "blocks": [{"type": "paragraph", "text": fallback_text}],
                    "text": fallback_text,
                }
            )

    total_chars = sum(len(item["text"]) for item in sections)
    if total_chars < 120:
        return {}

    return {
        "source_url": normalize_url(source_url),
        "page_title": page_title[:256],
        "section": section[:128],
        "breadcrumb_path": breadcrumb_path[:256],
        "crawled_at": crawled_at,
        "sections": sections,
    }


def crawl_docs(
    base_url: str = "https://www.kubeflow.org",
    crawl_delay: float = 0.0,
    max_pages: int = 0,
) -> List[Dict[str, object]]:
    """Crawl Kubeflow docs pages and return structured page records."""
    if requests is None or BeautifulSoup is None:
        raise RuntimeError("requests and beautifulsoup4 are required for docs crawling")
    session = requests.Session()
    session.headers.update({"User-Agent": DEFAULT_USER_AGENT})

    urls = discover_sitemap_urls(session, base_url)
    if not urls:
        logger.warning("Sitemap discovery returned no docs URLs; falling back to link crawl.")
        urls = discover_docs_links(session, base_url, crawl_delay=crawl_delay, max_pages=max_pages)

    if max_pages:
        urls = urls[:max_pages]

    page_records: List[Dict[str, object]] = []
    for index, url in enumerate(urls, start=1):
        try:
            response = session.get(url, timeout=30)
            response.raise_for_status()
        except Exception as exc:
            logger.warning("Failed to fetch %s: %s", url, exc)
            continue

        content_type = response.headers.get("Content-Type", "")
        if "html" not in content_type and "<html" not in response.text.lower():
            continue

        record = extract_sections_from_html(response.text, url)
        if record:
            page_records.append(record)

        if crawl_delay > 0:
            time.sleep(crawl_delay)

        if index % 50 == 0:
            logger.info("Crawled %d/%d URLs (%d valid pages)", index, len(urls), len(page_records))

    logger.info("Docs crawl complete: %d structured pages", len(page_records))
    return page_records


def save_pages(pages: Iterable[Dict[str, object]], output_path: str) -> None:
    """Save crawled page records to JSONL."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        for page in pages:
            handle.write(json.dumps(page, ensure_ascii=False) + "\n")
    logger.info("Saved docs crawl output to %s", output_path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    pages = crawl_docs(max_pages=5)
    logger.info("Sample pages: %d", len(pages))
    for page in pages[:3]:
        logger.info("  %s (%d sections)", page["source_url"], len(page.get("sections", [])))
