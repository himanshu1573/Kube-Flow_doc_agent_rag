import asyncio
import os
import json
import httpx
import re
from urllib.parse import urlparse

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
from typing import Dict, Any, List, Optional, AsyncGenerator, Tuple

from agent.core.retriever import build_tools_for_route, execute_tool_call
from agent.core.router import build_system_prompt, classify_question
from agent.core.state import THREAD_STORE

# Config
KSERVE_URL = os.getenv("KSERVE_URL", "http://llama.docs-agent.svc.cluster.local/openai/v1/chat/completions")
MODEL = os.getenv("MODEL", "llama3.1-8B")
PORT = int(os.getenv("PORT", "8000"))
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_API_KEY_HEADER = os.getenv("LLM_API_KEY_HEADER", "Authorization")
LLM_API_KEY_PREFIX = os.getenv("LLM_API_KEY_PREFIX", "Bearer")
# Output token budgets. Lower them for small per-minute token quotas (e.g. free LLM tiers).
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "1500"))
LLM_FOLLOWUP_MAX_TOKENS = int(os.getenv("LLM_FOLLOWUP_MAX_TOKENS", "1000"))
# Upper bound in seconds for honoring an upstream Retry-After header on HTTP 429.
LLM_MAX_RETRY_WAIT = float(os.getenv("LLM_MAX_RETRY_WAIT", "10"))
LLM_RATE_LIMIT_RETRIES = int(os.getenv("LLM_RATE_LIMIT_RETRIES", "2"))
# Bring-your-own-key: clients may send their own key for the configured LLM endpoint
# (X-LLM-API-Key) and optionally a model (X-LLM-Model). Keys are used for that request
# only and are never logged or stored. Set REQUIRE_CLIENT_API_KEY=true on public
# deployments so the server key is never spent on anonymous visitors.
ALLOW_CLIENT_API_KEYS = os.getenv("ALLOW_CLIENT_API_KEYS", "true").lower() == "true"
REQUIRE_CLIENT_API_KEY = os.getenv("REQUIRE_CLIENT_API_KEY", "false").lower() == "true"
CLIENT_API_KEY_PATTERN = re.compile(r"^[\x21-\x7e]{8,512}$")
CLIENT_MODEL_PATTERN = re.compile(r"^[A-Za-z0-9._:/@-]{1,128}$")

app = FastAPI(title="Kubeflow Agentic RAG API Service", version="2.0.0")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your actual domains
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    message: str
    stream: Optional[bool] = True
    thread_id: Optional[str] = None
    reset_thread: Optional[bool] = False
    context: Optional[Dict[str, Any]] = None

async def execute_tool(tool_call: Dict[str, Any]) -> tuple[str, List[str]]:
    """Execute a tool call and return the result and citations"""
    try:
        return execute_tool_call(tool_call)
    except Exception as e:
        print(f"[ERROR] Tool execution failed: {e}")
        return f"Tool execution failed: {e}", []


def build_fallback_tool_call(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Build a direct retrieval tool call when the LLM fails to emit valid tool JSON."""
    messages = payload.get("messages", [])
    user_message = next(
        (message.get("content", "") for message in reversed(messages) if message.get("role") == "user"),
        "",
    )
    if not user_message:
        return None

    tool_names = {
        tool.get("function", {}).get("name", "")
        for tool in payload.get("tools", [])
        if tool.get("type") == "function"
    }

    if tool_names == {"search_kubeflow_docs"}:
        tool_name = "search_kubeflow_docs"
        arguments = {"query": user_message, "top_k": 5}
    elif tool_names == {"search_kubeflow_code"}:
        tool_name = "search_kubeflow_code"
        arguments = {"query": user_message, "top_k": 5}
    else:
        tool_name = "search_kubeflow_context"
        arguments = {"query": user_message, "top_k": 5}

    return {
        "id": "fallback-tool-call",
        "type": "function",
        "function": {
            "name": tool_name,
            "arguments": json.dumps(arguments),
        },
    }

def build_llm_headers(api_key: str) -> Dict[str, str]:
    """Auth headers for the LLM endpoint using the configured header name and prefix."""
    if not api_key:
        return {}
    if LLM_API_KEY_HEADER.lower() == "authorization" and LLM_API_KEY_PREFIX:
        return {LLM_API_KEY_HEADER: f"{LLM_API_KEY_PREFIX} {api_key}"}
    return {LLM_API_KEY_HEADER: api_key}


def resolve_llm_credentials(
    client_api_key: Optional[str], client_model: Optional[str]
) -> Tuple[Dict[str, str], str]:
    """Pick the key and model for one request: the client's if allowed, else the server's."""
    client_api_key = (client_api_key or "").strip() if ALLOW_CLIENT_API_KEYS else ""
    client_model = (client_model or "").strip() if ALLOW_CLIENT_API_KEYS else ""

    if client_api_key and not CLIENT_API_KEY_PATTERN.match(client_api_key):
        raise HTTPException(status_code=400, detail="Malformed X-LLM-API-Key header.")
    if client_model and not CLIENT_MODEL_PATTERN.match(client_model):
        raise HTTPException(status_code=400, detail="Malformed X-LLM-Model header.")
    if REQUIRE_CLIENT_API_KEY and not client_api_key:
        raise HTTPException(
            status_code=401,
            detail="This deployment needs your own LLM API key. Add it in the assistant's API key settings.",
        )

    return build_llm_headers(client_api_key or LLM_API_KEY), client_model or MODEL


def retry_wait_seconds(retry_after: Optional[str], default: float = 2.0) -> float:
    """Seconds to wait before retrying a 429, honoring Retry-After within LLM_MAX_RETRY_WAIT."""
    try:
        wait = float(retry_after) if retry_after is not None else default
    except ValueError:
        wait = default
    return max(0.0, min(wait, LLM_MAX_RETRY_WAIT))


async def stream_llm_response(
    payload: Dict[str, Any],
    response_accumulator: Optional[Dict[str, Any]] = None,
    retry_count: int = 0,
    llm_headers: Optional[Dict[str, str]] = None,
) -> AsyncGenerator[str, None]:
    """Stream response from LLM and handle tool calls, yielding SSE events"""
    citations_collector = []
    if response_accumulator is None:
        response_accumulator = {"content": ""}
    if llm_headers is None:
        llm_headers = build_llm_headers(LLM_API_KEY)

    try:
        request_headers: Dict[str, str] = dict(llm_headers)

        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream("POST", KSERVE_URL, json=payload, headers=request_headers) as response:
                if response.status_code != 200:
                    error_body = (await response.aread()).decode("utf-8", "replace")[:500]
                    print(f"[ERROR] LLM HTTP {response.status_code}: {error_body}")
                    if response.status_code == 429 and retry_count < LLM_RATE_LIMIT_RETRIES:
                        await asyncio.sleep(retry_wait_seconds(response.headers.get("retry-after")))
                        async for retry_chunk in stream_llm_response(
                            payload,
                            response_accumulator,
                            retry_count=retry_count + 1,
                            llm_headers=llm_headers,
                        ):
                            yield retry_chunk
                        return

                    error_msg = f"LLM service error: HTTP {response.status_code}"
                    if response.status_code == 429:
                        error_msg += " (rate limit reached, retry shortly)"
                    elif response.status_code in (401, 403):
                        error_msg += " (the LLM provider rejected the API key)"
                    print(f"[ERROR] {error_msg}")
                    yield f"data: {json.dumps({'type': 'error', 'content': error_msg, 'status': response.status_code})}\n\n"
                    return
                
                # Buffer for accumulating tool calls
                tool_calls_buffer = {}
                
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    
                    data = line[6:]  # Remove "data: " prefix
                    if data == "[DONE]":
                        break
                    
                    try:
                        print(f"[DEBUG] Raw chunk: {data}")
                        chunk = json.loads(data)
                        if "error" in chunk:
                            error = chunk.get("error", {})
                            code = error.get("code")
                            failed_generation = error.get("failed_generation", "")

                            if code == "tool_use_failed":
                                fallback_tool_call = build_fallback_tool_call(payload)
                                if fallback_tool_call is None:
                                    yield f"data: {json.dumps({'type': 'error', 'content': 'Tool call fallback could not determine the user query.'})}\n\n"
                                    return

                                print("[TOOL] Falling back to direct retrieval after tool_use_failed")
                                result, tool_citations = await execute_tool(fallback_tool_call)
                                citations_collector.extend(tool_citations)
                                yield f"data: {json.dumps({'type': 'tool_result', 'tool_name': fallback_tool_call['function']['name'], 'content': result})}\n\n"

                                async for follow_up_chunk in handle_tool_follow_up(
                                    payload,
                                    [(fallback_tool_call, result)],
                                    citations_collector,
                                    response_accumulator,
                                    llm_headers,
                                ):
                                    yield follow_up_chunk
                                return

                            error_msg = error.get("message", "Unknown LLM streaming error")
                            if failed_generation:
                                error_msg = f"{error_msg} | failed_generation={failed_generation}"
                            print(f"[ERROR] {error_msg}")
                            yield f"data: {json.dumps({'type': 'error', 'content': error_msg})}\n\n"
                            return

                        choices = chunk.get("choices", [])
                        if not choices:
                            continue
                            
                        delta = choices[0].get("delta", {})
                        finish_reason = choices[0].get("finish_reason")
                        
                        # Handle tool calls in streaming
                        if "tool_calls" in delta:
                            tool_calls = delta["tool_calls"]
                            print(f"[DEBUG] Tool calls delta: {tool_calls}")
                            for tool_call in tool_calls:
                                index = tool_call.get("index", 0)
                                
                                # Initialize tool call buffer if needed
                                if index not in tool_calls_buffer:
                                    tool_calls_buffer[index] = {
                                        "id": tool_call.get("id", ""),
                                        "type": tool_call.get("type", "function"),
                                        "function": {
                                            "name": tool_call.get("function", {}).get("name", ""),
                                            "arguments": ""
                                        }
                                    }
                                
                                # Update tool call data
                                if tool_call.get("id"):
                                    tool_calls_buffer[index]["id"] = tool_call["id"]
                                if tool_call.get("type"):
                                    tool_calls_buffer[index]["type"] = tool_call["type"]
                                
                                function_data = tool_call.get("function", {})
                                if function_data.get("name"):
                                    tool_calls_buffer[index]["function"]["name"] = function_data["name"]
                                if "arguments" in function_data:
                                    tool_calls_buffer[index]["function"]["arguments"] += function_data["arguments"]
                        
                        # Handle regular content
                        elif "content" in delta and delta["content"]:
                            response_accumulator["content"] += delta["content"]
                            yield f"data: {json.dumps({'type': 'content', 'content': delta['content']})}\n\n"
                        
                        # Handle finish reason - execute tools if needed
                        if finish_reason == "tool_calls":
                            print(f"[TOOL] Finish reason: tool_calls, executing {len(tool_calls_buffer)} tools")

                            # Execute every requested tool first, then send all results
                            # back in a single follow-up request.
                            tool_results = []
                            for tool_call in tool_calls_buffer.values():
                                if tool_call["function"]["name"] and tool_call["function"]["arguments"]:
                                    print(f"[TOOL] Executing: {tool_call['function']['name']}")
                                    print(f"[TOOL] Arguments: {tool_call['function']['arguments']}")

                                    result, tool_citations = await execute_tool(tool_call)

                                    # DEBUG LOG
                                    print(f"[TOOL-RESULT] Name: {tool_call['function']['name']}")
                                    print(f"[TOOL-RESULT] Length: {len(result)} chars")
                                    print(f"[TOOL-RESULT] Citations: {len(tool_citations)}")

                                    # Collect citations
                                    citations_collector.extend(tool_citations)

                                    # Send tool execution result
                                    yield f"data: {json.dumps({'type': 'tool_result', 'tool_name': tool_call['function']['name'], 'content': result})}\n\n"
                                    tool_results.append((tool_call, result))

                            if tool_results:
                                async for follow_up_chunk in handle_tool_follow_up(
                                    payload,
                                    tool_results,
                                    citations_collector,
                                    response_accumulator,
                                    llm_headers,
                                ):
                                    yield follow_up_chunk

                            tool_calls_buffer.clear()
                            break  # Tool execution complete, exit streaming loop
                            
                    except json.JSONDecodeError as e:
                        print(f"[ERROR] JSON decode error: {e}, line: {line}")
                        continue
        
        # Send citations if any were collected
        if citations_collector:
            # Remove duplicates while preserving order
            unique_citations = []
            for citation in citations_collector:
                if citation not in unique_citations:
                    unique_citations.append(citation)
            
            yield f"data: {json.dumps({'type': 'citations', 'citations': unique_citations})}\n\n"
        
        # Send completion signal
        yield f"data: {json.dumps({'type': 'done'})}\n\n"
                        
    except Exception as e:
        print(f"[ERROR] Streaming failed: {e}")
        yield f"data: {json.dumps({'type': 'error', 'content': f'Streaming failed: {e}'})}\n\n"

async def handle_tool_follow_up(
    original_payload: Dict[str, Any],
    tool_results: List[Tuple[Dict[str, Any], str]],
    citations_collector: List[str],
    response_accumulator: Dict[str, Any],
    llm_headers: Optional[Dict[str, str]] = None,
) -> AsyncGenerator[str, None]:
    """Handle the single follow-up request after all tool calls have executed"""
    try:
        print(f"[TOOL] Handling follow-up request with {len(tool_results)} tool results")

        # Create messages with tool call and result
        messages = original_payload["messages"].copy()

        # One assistant turn carrying every tool call, as the OpenAI API expects
        messages.append({
            "role": "assistant",
            "tool_calls": [tool_call for tool_call, _ in tool_results]
        })

        # One tool message per call, matched by tool_call_id
        for tool_call, tool_result in tool_results:
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": tool_result
            })
        
        # Create follow-up payload - remove tools to get final response
        follow_up_payload = {
            "model": original_payload["model"],
            "messages": messages,
            "stream": True,
            "max_tokens": LLM_FOLLOWUP_MAX_TOKENS
        }
        
        # Stream the follow-up response
        async for chunk in stream_llm_response(
            follow_up_payload, response_accumulator, llm_headers=llm_headers
        ):
            yield chunk
        
    except Exception as e:
        print(f"[ERROR] Tool follow-up failed: {e}")
        yield f"data: {json.dumps({'type': 'error', 'content': f'Tool follow-up failed: {e}'})}\n\n"

async def get_non_streaming_response(
    payload: Dict[str, Any], llm_headers: Optional[Dict[str, str]] = None
) -> tuple[str, List[str]]:
    """Get non-streaming response by collecting all streaming chunks"""
    response_content = ""
    citations = []
    response_accumulator = {"content": ""}
    
    async for chunk in stream_llm_response(payload, response_accumulator, llm_headers=llm_headers):
        if chunk.startswith("data: "):
            try:
                data = json.loads(chunk[6:].strip())
                if data.get("type") == "content":
                    response_content += data.get("content", "")
                elif data.get("type") == "citations":
                    citations.extend(data.get("citations", []))
                elif data.get("type") == "error":
                    # Surface rate limits as 429, rejected keys as 401, other LLM failures as 502.
                    upstream = data.get("status")
                    status = 429 if upstream == 429 else 401 if upstream in (401, 403) else 502
                    raise HTTPException(status_code=status, detail=data.get("content", "Unknown error"))
            except json.JSONDecodeError:
                continue
    
    return response_content or response_accumulator["content"], citations

@app.get("/")
async def hello():
    """Simple hello endpoint"""
    return {"message": "Hello from Kubeflow Agentic RAG API!", "service": "https-api"}

@app.get("/health")
async def health_check():
    """Health check endpoint for Kubernetes probes"""
    return {"status": "healthy", "service": "https-api"}

@app.get("/config")
async def client_config():
    """Public settings the widget needs to decide whether to ask for the user's key"""
    return {
        "model": MODEL,
        "llm_provider_host": urlparse(KSERVE_URL).hostname or "",
        "allow_client_api_keys": ALLOW_CLIENT_API_KEYS,
        "require_client_api_key": REQUIRE_CLIENT_API_KEY,
        "server_api_key_configured": bool(LLM_API_KEY),
    }

@app.options("/chat")
async def options_chat():
    """Handle preflight OPTIONS request"""
    return {"message": "OK"}

@app.options("/")
async def options_root():
    """Handle preflight OPTIONS request for root"""
    return {"message": "OK"}

@app.options("/health")
async def options_health():
    """Handle preflight OPTIONS request for health"""
    return {"message": "OK"}

@app.post("/chat")
async def chat(
    request: ChatRequest,
    x_llm_api_key: Optional[str] = Header(default=None),
    x_llm_model: Optional[str] = Header(default=None),
):
    """Chat endpoint with RAG capabilities - supports both streaming and non-streaming"""
    try:
        print(f"[CHAT] Processing message: {request.message[:100]}...")
        llm_headers, model = resolve_llm_credentials(x_llm_api_key, x_llm_model)
        if request.reset_thread and request.thread_id:
            THREAD_STORE.clear(request.thread_id)

        # Enrich routing with page context if available
        routing_message = request.message
        if request.context and request.context.get("title"):
            routing_message = f"User is on page '{request.context['title']}'. Query: {request.message}"

        route_decision = classify_question(routing_message)
        system_prompt = build_system_prompt(route_decision)
        
        # Add page context to system prompt if available
        if request.context:
            ctx_hint = f"\n\nUser is currently viewing: {request.context.get('title', 'Unknown Page')} ({request.context.get('path', '')})"
            system_prompt += ctx_hint

        thread_id = THREAD_STORE.ensure_thread(system_prompt, request.thread_id)
        THREAD_STORE.append(thread_id, "user", request.message)
        
        # Create initial payload
        payload = {
            "model": model,
            "messages": THREAD_STORE.get_messages(thread_id),
            "tools": build_tools_for_route(route_decision.target),
            "tool_choice": "auto",
            "stream": True,
            "max_tokens": LLM_MAX_TOKENS
        }
        
        if request.stream:
            response_accumulator = {"content": ""}

            async def event_stream() -> AsyncGenerator[str, None]:
                yield f"data: {json.dumps({'type': 'thread', 'thread_id': thread_id, 'route': route_decision.target})}\n\n"
                async for chunk in stream_llm_response(payload, response_accumulator, llm_headers=llm_headers):
                    yield chunk
                if response_accumulator["content"].strip():
                    THREAD_STORE.append(thread_id, "assistant", response_accumulator["content"].strip())

            # Return streaming response using Server-Sent Events
            return StreamingResponse(
                event_stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Headers": "Cache-Control"
                }
            )
        else:
            # Return non-streaming JSON response
            response_content, citations = await get_non_streaming_response(payload, llm_headers)
            if response_content.strip():
                THREAD_STORE.append(thread_id, "assistant", response_content.strip())
            
            # Remove duplicates from citations while preserving order
            unique_citations = []
            for citation in citations:
                if citation not in unique_citations:
                    unique_citations.append(citation)
            
            return {
                "thread_id": thread_id,
                "route": route_decision.target,
                "response": response_content,
                "citations": unique_citations if unique_citations else None
            }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] Chat handling failed: {e}")
        raise HTTPException(status_code=500, detail=f"Request failed: {e}")

if __name__ == "__main__":
    print("🚀 Starting Kubeflow Agent HTTP API Server")
    print(f"   Port: {PORT}")
    print(f"   LLM Service: {KSERVE_URL}")
    
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=PORT
    )
