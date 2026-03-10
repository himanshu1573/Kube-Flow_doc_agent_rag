import os
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pymilvus import MilvusClient
from sentence_transformers import SentenceTransformer


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

PORT = int(os.getenv("PORT", "8000"))
MILVUS_URI = os.getenv("MILVUS_URI", "http://milvus.docs-agent.svc.cluster.local:19530")
MILVUS_COLLECTION = os.getenv("MILVUS_COLLECTION", "kubeflow_pdf_rag")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "").strip().lower()
LLM_CHAT_URL = os.getenv("LLM_CHAT_URL", "")
LLM_MODEL = os.getenv("LLM_MODEL", "")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_BASE_URL = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")

SYSTEM_PROMPT = (
    "You are a Kubeflow documentation assistant. Answer using only the retrieved context. "
    "If the answer is not in the context, say that clearly. Cite the sources you used."
)


app = FastAPI(title="Kubeflow Docs Agent RAG", version="0.2.0")
encoder = SentenceTransformer(EMBEDDING_MODEL)

if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=10)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=16000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    history: List[ChatMessage] = Field(default_factory=list)
    top_k: int = Field(default=5, ge=1, le=10)
    max_tokens: int = Field(default=512, ge=64, le=2048)


def configured_provider() -> str:
    if LLM_PROVIDER:
        return LLM_PROVIDER
    if GEMINI_API_KEY:
        return "gemini"
    if LLM_CHAT_URL:
        return "openai-compatible"
    return "none"


def configured_model() -> str:
    provider = configured_provider()
    if provider == "gemini":
        return GEMINI_MODEL
    if provider == "openai-compatible":
        return LLM_MODEL
    return ""


def milvus_client() -> MilvusClient:
    return MilvusClient(uri=MILVUS_URI)


def search_docs(query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    query_vector = encoder.encode(query).tolist()
    client = milvus_client()

    try:
        results = client.search(
            collection_name=MILVUS_COLLECTION,
            data=[query_vector],
            limit=top_k,
            output_fields=["content_text", "file_path", "citation_url", "title", "chunk_index"],
            search_params={"metric_type": "IP"},
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Milvus search failed: {exc}") from exc

    hits: List[Dict[str, Any]] = []
    for item in results[0]:
        entity = item.get("entity", {})
        hits.append(
            {
                "score": item.get("distance", 0.0),
                "content_text": entity.get("content_text", ""),
                "file_path": entity.get("file_path", ""),
                "citation_url": entity.get("citation_url", ""),
                "title": entity.get("title", ""),
                "chunk_index": entity.get("chunk_index", 0),
            }
        )
    return hits


def build_context(hits: List[Dict[str, Any]]) -> str:
    sections = []
    for index, hit in enumerate(hits, start=1):
        sections.append(
            f"[{index}] {hit['title']}\n"
            f"Source: {hit['citation_url']}\n"
            f"Content: {hit['content_text']}"
        )
    return "\n\n".join(sections)


def history_as_openai_messages(history: List[ChatMessage]) -> List[Dict[str, str]]:
    return [{"role": message.role, "content": message.content} for message in history]


def history_as_gemini_contents(history: List[ChatMessage]) -> List[Dict[str, Any]]:
    contents: List[Dict[str, Any]] = []
    for message in history:
        contents.append(
            {
                "role": "model" if message.role == "assistant" else "user",
                "parts": [{"text": message.content}],
            }
        )
    return contents


async def call_openai_compatible(
    question: str,
    context: str,
    history: List[ChatMessage],
    max_tokens: int,
) -> Optional[str]:
    if not LLM_CHAT_URL:
        return None

    headers = {"Content-Type": "application/json"}
    if LLM_API_KEY:
        headers["Authorization"] = f"Bearer {LLM_API_KEY}"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *history_as_openai_messages(history),
        {
            "role": "user",
            "content": (
                "Use the context below to answer the question.\n\n"
                f"Context:\n{context}\n\nQuestion:\n{question}"
            ),
        },
    ]
    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.2,
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(LLM_CHAT_URL, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    choices = data.get("choices", [])
    if not choices:
        return None
    return choices[0].get("message", {}).get("content")


async def call_gemini(
    question: str,
    context: str,
    history: List[ChatMessage],
    max_tokens: int,
) -> Optional[str]:
    if not GEMINI_API_KEY:
        return None

    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [
            *history_as_gemini_contents(history),
            {
                "role": "user",
                "parts": [
                    {
                        "text": (
                            "Use the context below to answer the question.\n\n"
                            f"Context:\n{context}\n\nQuestion:\n{question}"
                        )
                    }
                ],
            },
        ],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": max_tokens,
        },
    }

    url = f"{GEMINI_BASE_URL}/models/{GEMINI_MODEL}:generateContent"
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY,
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    candidates = data.get("candidates", [])
    if not candidates:
        return None

    parts = candidates[0].get("content", {}).get("parts", [])
    text_segments = [part.get("text", "") for part in parts if part.get("text")]
    return "\n".join(segment for segment in text_segments if segment).strip() or None


async def call_llm(
    question: str,
    context: str,
    history: List[ChatMessage],
    max_tokens: int,
) -> Optional[str]:
    provider = configured_provider()

    if provider == "gemini":
        return await call_gemini(question, context, history, max_tokens)
    if provider == "openai-compatible":
        return await call_openai_compatible(question, context, history, max_tokens)
    return None


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/config")
def config() -> Dict[str, Any]:
    provider = configured_provider()
    return {
        "provider": provider,
        "model": configured_model(),
        "collection": MILVUS_COLLECTION,
        "llm_configured": provider != "none",
    }


@app.get("/health")
def health() -> Dict[str, Any]:
    try:
        client = milvus_client()
        has_collection = client.has_collection(MILVUS_COLLECTION)
    except Exception as exc:
        return {"status": "degraded", "milvus": False, "detail": str(exc)}

    provider = configured_provider()
    return {
        "status": "ok",
        "milvus": True,
        "collection_exists": has_collection,
        "llm_provider": provider,
        "llm_configured": provider != "none",
        "model": configured_model(),
    }


@app.post("/search")
def search(request: SearchRequest) -> Dict[str, Any]:
    hits = search_docs(request.query, request.top_k)
    return {"query": request.query, "results": hits}


@app.post("/chat")
async def chat(request: ChatRequest) -> Dict[str, Any]:
    hits = search_docs(request.message, request.top_k)
    context = build_context(hits)
    citations = [hit["citation_url"] for hit in hits if hit.get("citation_url")]

    generated_answer = await call_llm(
        question=request.message,
        context=context,
        history=request.history,
        max_tokens=request.max_tokens,
    )
    if generated_answer is None:
        generated_answer = (
            "LLM is not configured. Returning retrieved documentation context only.\n\n"
            f"{context}"
        )

    return {
        "answer": generated_answer,
        "citations": citations,
        "results": hits,
        "provider": configured_provider(),
        "model": configured_model(),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
