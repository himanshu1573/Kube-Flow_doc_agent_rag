"""Baseline Google ADK blueprint for the Kubeflow Phase 2 router."""

from agent.core.retriever import search_context
from agent.core.router import classify_question


def retrieve_kubeflow_context(query: str, target: str = "auto") -> str:
    formatted, _, route = search_context(query=query, top_k=5, target=target)
    return f"[route={route.target}]\\n{formatted}"


def plan_route(query: str) -> dict:
    decision = classify_question(query)
    return {
        "target": decision.target,
        "reason": decision.reason,
        "route_hint": decision.route_hint,
    }


# This file is intentionally lightweight and framework-agnostic so that the
# final ADK agent wiring can import these helpers directly.
