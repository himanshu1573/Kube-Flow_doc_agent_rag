"""Semantic routing helpers for Phase 2 docs-vs-code intent detection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pipelines.shared.retrieval_strategy import analyze_query

RouteTarget = Literal["docs", "code", "hybrid"]


@dataclass(frozen=True)
class RouteDecision:
    """Resolved route decision for a user query."""

    target: RouteTarget
    reason: str
    route_hint: str
    query_analysis: dict


BASE_SYSTEM_PROMPT = """
You are the Kubeflow Agentic RAG Assistant.

Role
- Answer Kubeflow questions using grounded retrieval.
- For conceptual, installation, architecture, and how-to questions, prefer documentation retrieval.
- For debugging, manifests, YAML, RBAC, webhook, Helm, Kustomize, or configuration questions, prefer code retrieval.
- If the query is ambiguous or spans both concepts and implementation, combine both when needed.

Tool Use
- Prefer `search_kubeflow_context` first. It can route automatically or honor an explicit target.
- Use `search_kubeflow_docs` when the answer should come from official docs pages.
- Use `search_kubeflow_code` when the answer should come from manifests or code snippets.
- Never expose raw tool call JSON to the user.
- Summarize retrieved results in your own words and cite the provided URLs.

Style
- Be concise and grounded.
- Use Markdown.
- If the retrieved context is insufficient, say so directly.
- Prefer crisp, actionable answers over generic summaries.
""".strip()


def build_answer_style_hint(query_analysis: dict) -> str:
    """Build answer-format guidance based on the detected query intent."""
    query_type = str(query_analysis.get("query_type", "general"))
    wants_code_examples = bool(query_analysis.get("wants_code_examples"))
    wants_steps = bool(query_analysis.get("wants_steps"))
    wants_commands = bool(query_analysis.get("wants_commands"))

    instructions = []

    if query_type == "definition":
        instructions.append(
            "- Start with a direct one- or two-sentence definition before adding details."
        )
    if query_type in {"install", "how_to"} or wants_steps:
        instructions.append(
            "- Structure the answer as: what this is, steps, commands if available, then sources."
        )
    if wants_code_examples or wants_commands:
        instructions.append(
            "- When the user asks for code, YAML, or commands, provide the concrete snippet or command first if the retrieved context supports it."
        )
        instructions.append(
            "- Prefer manifest snippets, kubectl commands, Helm commands, or YAML examples over abstract explanation."
        )
    if query_type == "compare":
        instructions.append(
            "- Compare the requested items explicitly with a short side-by-side explanation."
        )

    if not instructions:
        instructions.append("- Answer directly using the strongest grounded evidence first.")

    return "Answer format guidance:\n" + "\n".join(instructions)


def classify_question(question: str) -> RouteDecision:
    """Classify a question into docs, code, or hybrid retrieval."""
    analysis = analyze_query(question)
    query_type = str(analysis.get("query_type", "general"))
    wants_code_examples = bool(analysis.get("wants_code_examples"))
    wants_steps = bool(analysis.get("wants_steps"))
    config_code_markers = (
        "yaml",
        "manifest",
        "webhook",
        "rbac",
        "configmap",
        "kustomize",
        "helm",
    )
    is_configuration_question = any(marker in question.lower() for marker in config_code_markers)

    if analysis.get("strongly_prefer_code") and query_type not in {"install", "how_to"}:
        target: RouteTarget = "code"
        reason = "The query contains strong code or manifest signals."
    elif analysis.get("prefer_code") and is_configuration_question:
        target = "code"
        reason = "The query is a configuration or manifest question and should prefer code."
    elif wants_code_examples and not wants_steps:
        target = "code"
        reason = "The query explicitly asks for code, YAML, manifests, or commands."
    elif wants_code_examples and analysis.get("prefer_docs"):
        target = "hybrid"
        reason = "The query asks for both documentation guidance and concrete code or commands."
    elif analysis.get("prefer_code") and analysis.get("prefer_docs"):
        target = "hybrid"
        reason = "The query covers both conceptual and implementation details."
    elif analysis.get("prefer_code"):
        target = "code"
        reason = "The query looks implementation or debugging focused."
    elif analysis.get("prefer_docs"):
        target = "docs"
        reason = "The query looks conceptual or documentation focused."
    else:
        target = "hybrid"
        reason = "The query is ambiguous or may need both docs and code context."

    route_hint = (
        f"Router decision: {target}. {reason} "
        f"Priority terms: {' '.join(analysis.get('priority_terms', [])[:12])}."
    )
    return RouteDecision(
        target=target,
        reason=reason,
        route_hint=route_hint,
        query_analysis=analysis,
    )


def build_system_prompt(route_decision: RouteDecision) -> str:
    """Build the live system prompt with an explicit router hint."""
    answer_style_hint = build_answer_style_hint(route_decision.query_analysis)
    return f"{BASE_SYSTEM_PROMPT}\n\n{route_decision.route_hint}\n{answer_style_hint}"
