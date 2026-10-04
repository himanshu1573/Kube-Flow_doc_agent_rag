import os

from fastmcp import FastMCP

from agent.core.retriever import format_hits, search_code, search_context, search_docs

PORT = int(os.getenv("PORT", "8000"))

mcp = FastMCP("Kubeflow Agentic RAG MCP Server")


@mcp.tool()
def search_kubeflow_context(
    query: str,
    top_k: int = 5,
    target: str = "auto",
) -> str:
    """Search Kubeflow docs, manifests, or both with shared routing."""
    try:
        formatted, _, route = search_context(query=query, top_k=top_k, target=target)
        return f"[ROUTE]\nTarget: {route.target}\nReason: {route.reason}\n\n{formatted}"
    except Exception as exc:
        return f"search_kubeflow_context failed: {exc}"


@mcp.tool()
def search_kubeflow_docs(query: str, top_k: int = 5) -> str:
    """Search the official Kubeflow documentation collection."""
    try:
        hits, _ = search_docs(query=query, top_k=top_k)
        return format_hits(hits)[0]
    except Exception as exc:
        return f"search_kubeflow_docs failed: {exc}"


@mcp.tool()
def search_kubeflow_code(query: str, top_k: int = 5) -> str:
    """Search Kubeflow release code for YAML, RBAC, Helm, and implementation details."""
    try:
        hits, _ = search_code(query=query, top_k=top_k)
        return format_hits(hits)[0]
    except Exception as exc:
        return f"search_kubeflow_code failed: {exc}"


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=PORT)
