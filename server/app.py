import os
import json
import asyncio
import httpx
import websockets
from websockets.server import serve
from websockets.exceptions import ConnectionClosedError
import logging
from typing import Dict, Any, List

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

async def execute_tool(tool_call: Dict[str, Any]) -> tuple[str, List[str]]:
    """Execute a tool call and return the result and citations"""
    try:
        return execute_tool_call(tool_call)
    except Exception as e:
        print(f"[ERROR] Tool execution failed: {e}")
        return f"Tool execution failed: {e}", []

async def stream_llm_response(
    payload: Dict[str, Any],
    websocket,
    citations_collector: List[str] = None,
    response_accumulator: Dict[str, Any] | None = None,
) -> None:
    """Stream response from LLM to websocket, handling tool calls"""
    if citations_collector is None:
        citations_collector = []
    if response_accumulator is None:
        response_accumulator = {"content": ""}
    try:
        request_headers: Dict[str, str] = {}
        if LLM_API_KEY:
            if LLM_API_KEY_HEADER.lower() == "authorization" and LLM_API_KEY_PREFIX:
                request_headers[LLM_API_KEY_HEADER] = f"{LLM_API_KEY_PREFIX} {LLM_API_KEY}"
            else:
                request_headers[LLM_API_KEY_HEADER] = LLM_API_KEY

        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream("POST", KSERVE_URL, json=payload, headers=request_headers) as response:
                if response.status_code != 200:
                    error_msg = f"LLM service error: HTTP {response.status_code}"
                    print(f"[ERROR] {error_msg}")
                    await websocket.send(json.dumps({"type": "error", "content": error_msg}))
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
                        chunk = json.loads(data)
                        choices = chunk.get("choices", [])
                        if not choices:
                            continue
                            
                        delta = choices[0].get("delta", {})
                        finish_reason = choices[0].get("finish_reason")
                        
                        # Handle tool calls in streaming
                        if "tool_calls" in delta:
                            tool_calls = delta["tool_calls"]
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
                            await websocket.send(json.dumps({
                                "type": "content", 
                                "content": delta["content"]
                            }))
                        
                        # Handle finish reason - execute tools if needed
                        if finish_reason == "tool_calls":
                            print(f"[TOOL] Finish reason: tool_calls, executing {len(tool_calls_buffer)} tools")
                            
                            # Execute all accumulated tool calls
                            for tool_call in tool_calls_buffer.values():
                                if tool_call["function"]["name"] and tool_call["function"]["arguments"]:
                                    try:
                                        print(f"[TOOL] Executing: {tool_call['function']['name']}")
                                        print(f"[TOOL] Arguments: {tool_call['function']['arguments']}")
                                        
                                        result, tool_citations = await execute_tool(tool_call)
                                        
                                        # Collect citations
                                        citations_collector.extend(tool_citations)
                                        
                                        # Send tool execution result to client
                                        await websocket.send(json.dumps({
                                            "type": "tool_result",
                                            "tool_name": tool_call["function"]["name"],
                                            "content": result
                                        }))
                                        
                                        # Make follow-up request with tool results
                                        await handle_tool_follow_up(
                                            payload,
                                            tool_call,
                                            result,
                                            websocket,
                                            citations_collector,
                                            response_accumulator,
                                        )
                                        
                                    except Exception as e:
                                        print(f"[ERROR] Tool execution error: {e}")
                                        await websocket.send(json.dumps({
                                            "type": "error",
                                            "content": f"Tool execution failed: {e}"
                                        }))
                            
                            tool_calls_buffer.clear()
                            break  # Tool execution complete, exit streaming loop
                            
                    except json.JSONDecodeError as e:
                        print(f"[ERROR] JSON decode error: {e}, line: {line}")
                        continue
                        
    except Exception as e:
        print(f"[ERROR] Streaming failed: {e}")
        await websocket.send(json.dumps({"type": "error", "content": f"Streaming failed: {e}"}))

async def handle_tool_follow_up(
    original_payload: Dict[str, Any],
    tool_call: Dict[str, Any],
    tool_result: str,
    websocket,
    citations_collector: List[str] = None,
    response_accumulator: Dict[str, Any] | None = None,
) -> None:
    """Handle follow-up request after tool execution"""
    if citations_collector is None:
        citations_collector = []
    if response_accumulator is None:
        response_accumulator = {"content": ""}
    try:
        print("[TOOL] Handling follow-up request with tool results")
        
        # Create messages with tool call and result
        messages = original_payload["messages"].copy()
        
        # Add assistant's tool call message
        messages.append({
            "role": "assistant",
            "tool_calls": [tool_call]
        })
        
        # Add tool result message
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
            "max_tokens": 1000
        }
        
        # Stream the follow-up response
        await stream_llm_response(
            follow_up_payload,
            websocket,
            citations_collector,
            response_accumulator,
        )
        
    except Exception as e:
        print(f"[ERROR] Tool follow-up failed: {e}")
        await websocket.send(json.dumps({"type": "error", "content": f"Tool follow-up failed: {e}"}))

async def handle_chat(
    message: str,
    websocket,
    thread_id: str | None = None,
    reset_thread: bool = False,
    context: Dict[str, Any] | None = None,
) -> None:
    """Handle chat with tool calling support"""
    try:
        print(f"[CHAT] Processing message: {message[:100]}...")
        if reset_thread and thread_id:
            THREAD_STORE.clear(thread_id)

        # Enrich routing with page context if available
        routing_message = message
        if context and context.get("title"):
            routing_message = f"User is on page '{context['title']}'. Query: {message}"

        route_decision = classify_question(routing_message)
        system_prompt = build_system_prompt(route_decision)

        # Add page context to system prompt if available
        if context:
            ctx_hint = f"\n\nUser is currently viewing: {context.get('title', 'Unknown Page')} ({context.get('path', '')})"
            system_prompt += ctx_hint

        thread_id = THREAD_STORE.ensure_thread(system_prompt, thread_id)
        THREAD_STORE.append(thread_id, "user", message)
        
        # Create initial payload
        payload = {
            "model": MODEL,
            "messages": THREAD_STORE.get_messages(thread_id),
            "tools": build_tools_for_route(route_decision.target),
            "tool_choice": "auto",
            "stream": True,
            "max_tokens": 1500
        }
        
        # Collect citations throughout the conversation
        citations_collector = []
        response_accumulator = {"content": ""}

        await websocket.send(json.dumps({
            "type": "thread",
            "thread_id": thread_id,
            "route": route_decision.target,
        }))
        
        # Start streaming response
        await stream_llm_response(
            payload,
            websocket,
            citations_collector,
            response_accumulator,
        )

        if response_accumulator["content"].strip():
            THREAD_STORE.append(thread_id, "assistant", response_accumulator["content"].strip())
        
        # Send citations if any were collected
        if citations_collector:
            # Remove duplicates while preserving order
            unique_citations = []
            for citation in citations_collector:
                if citation not in unique_citations:
                    unique_citations.append(citation)
            
            await websocket.send(json.dumps({
                "type": "citations", 
                "citations": unique_citations
            }))
        
        # Send completion signal
        await websocket.send(json.dumps({"type": "done"}))
        
    except Exception as e:
        print(f"[ERROR] Chat handling failed: {e}")
        await websocket.send(json.dumps({"type": "error", "content": f"Request failed: {e}"}))

async def handle_websocket(websocket, path):
    """Handle WebSocket connections"""
    print(f"[WS] New connection from {websocket.remote_address}")
    
    try:
        # Send welcome message
        await websocket.send(json.dumps({
            "type": "system",
            "content": "Connected to Kubeflow Documentation Assistant"
        }))
        
        async for message in websocket:
            try:
                # Ensure we always deal with string, not bytes
                if isinstance(message, (bytes, bytearray)):
                    message = message.decode("utf-8", errors="ignore")

                # Try to parse as JSON first
                try:
                    msg_data = json.loads(message)
                    if isinstance(msg_data, dict) and "message" in msg_data:
                        thread_id = msg_data.get("thread_id")
                        reset_thread = bool(msg_data.get("reset_thread", False))
                        context = msg_data.get("context")
                        message = msg_data["message"]
                    else:
                        thread_id = None
                        reset_thread = False
                        context = None
                except json.JSONDecodeError:
                    # Treat as plain text message
                    thread_id = None
                    reset_thread = False
                    context = None

                print(f"[WS] Received: {message[:100]}...")
                await handle_chat(message, websocket, thread_id, reset_thread, context)
                
            except Exception as e:
                print(f"[ERROR] Message processing error: {e}")
                await websocket.send(json.dumps({
                    "type": "error", 
                    "content": f"Message processing failed: {e}"
                }))
                
    except ConnectionClosedError:
        print("[WS] Connection closed")
    except Exception as e:
        print(f"[ERROR] WebSocket error: {e}")

async def health_check(path, request_headers):
    """Handle HTTP health checks"""
    if path == "/health":
        return 200, [("Content-Type", "text/plain")], b"OK"
    return None

async def main():
    """Start the WebSocket server"""
    print("🚀 Starting Kubeflow Agent WebSocket Server")
    print(f"   Port: {PORT}")
    print(f"   LLM Service: {KSERVE_URL}")
    
    # Configure logging
    logging.getLogger("websockets").setLevel(logging.WARNING)
    
    # Start server
    async with serve(
        handle_websocket, 
        "0.0.0.0", 
        PORT,
        process_request=health_check,
        ping_interval=30,
        ping_timeout=10
    ):
        print("✅ WebSocket server is running...")
        print(f"   WebSocket: ws://localhost:{PORT}")
        print(f"   Health: http://localhost:{PORT}/health")
        
        # Keep server running
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
