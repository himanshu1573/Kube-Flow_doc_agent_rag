"""
Shared retrieval strategy helpers for docs-agent search and validation.

This module adds lightweight hybrid-retrieval behavior on top of vector search:
  - query expansion for manifest-heavy questions
  - collection preference inference (docs vs code)
  - path/domain-aware reranking of candidate hits
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Dict, Iterable, List

PATH_ALIAS_HINTS = {
    "common/istio": [
        "istio",
        "service mesh",
        "gateway",
        "authorization policy",
        "peer authentication",
        "virtual service",
        "sidecar",
        "envoy",
        "mtls",
        "ingress",
    ],
    "common/knative": [
        "knative",
        "serving",
        "eventing",
        "serverless",
        "scale to zero",
        "activator",
        "revision",
        "service",
        "net istio",
        "webhook",
    ],
    "common/dex": [
        "dex",
        "oidc",
        "oauth2",
        "authentication",
        "identity provider",
        "connector",
        "login",
    ],
    "common/cert-manager": [
        "cert manager",
        "certificate",
        "issuer",
        "clusterissuer",
        "cainjector",
        "tls",
        "webhook",
    ],
    "applications/pipeline": [
        "kubeflow pipelines",
        "kfp",
        "pipeline api server",
        "deployment",
        "service",
        "configmap",
        "role",
        "rolebinding",
        "serviceaccount",
        "crd",
        "webhook",
        "scheduled workflow",
    ],
    "applications/profiles": [
        "profiles",
        "namespaces",
        "rbac",
        "rolebinding",
        "serviceaccount",
        "user profile",
    ],
    "tests": [
        "tests",
        "e2e",
        "integration",
        "validation",
        "presubmit",
    ],
}

QUERY_EXPANSIONS = {
    "istio": [
        "istio",
        "service mesh",
        "gateway",
        "authorization policy",
        "peer authentication",
        "virtual service",
        "mtls",
    ],
    "knative": [
        "knative",
        "serving",
        "eventing",
        "serverless",
        "scale to zero",
        "activator",
        "revision",
    ],
    "dex": [
        "dex",
        "oidc",
        "oauth2",
        "authentication",
        "identity provider",
        "connector",
    ],
    "cert-manager": [
        "cert manager",
        "certificate",
        "issuer",
        "clusterissuer",
        "cainjector",
        "tls",
    ],
    "component": [
        "dsl component",
        "lightweight python component",
        "lightweight python components",
        "containerized python component",
        "base image",
        "@dsl.component",
    ],
    "compile": [
        "compile pipeline",
        "pipeline compiler",
        "kfp compiler",
        "pipeline yaml",
        "compiler compile",
    ],
    "resources": [
        "deployment",
        "service",
        "configmap",
        "role",
        "rolebinding",
        "serviceaccount",
        "custom resource definition",
    ],
    "testing": [
        "tests",
        "e2e",
        "integration",
        "validation",
        "presubmit",
    ],
}

CODE_INTENT_TERMS = {
    "yaml",
    "manifest",
    "manifests",
    "deployment",
    "deployments",
    "service",
    "services",
    "configmap",
    "configmaps",
    "rolebinding",
    "clusterrolebinding",
    "clusterrole",
    "serviceaccount",
    "crd",
    "resources",
    "rbac",
    "istio",
    "knative",
    "dex",
    "cert",
    "cert-manager",
    "namespace",
    "namespaces",
    "authorizationpolicy",
    "authorizationpolicies",
    "clustertrainingruntime",
    "clusterservingruntimes",
    "pvcviewer",
    "networkpolicy",
    "horizontalpodautoscaler",
    "webhook",
    "kustomization",
    "dockerfile",
    "helm",
    "code",
    "snippet",
    "snippets",
    "example",
    "examples",
}

# Stronger signal terms that definitively mean the user wants code/manifest
# results rather than documentation pages.
STRONG_CODE_TERMS = {
    "authorizationpolicy", "authorizationpolicies",
    "clusterrolebinding", "clusterrole",
    "clustertrainingruntime", "clusterservingruntimes",
    "clusterservingruntime",
    "pvcviewer", "networkpolicy",
    "kustomization", "dockerfile",
    "helm", "cache server",
    "metadata service", "metadata-grpc",
}

DOCS_INTENT_TERMS = {
    "how",
    "what",
    "overview",
    "introduction",
    "guide",
    "concept",
    "architecture",
    "tutorial",
    "install",
    "installation",
}

QUERY_TYPE_PATTERNS = {
    "compare": re.compile(r"\b(compare|difference between|vs\.?|versus)\b", re.IGNORECASE),
    "install": re.compile(r"\b(install|installation|set up|setup|deploy|get started)\b", re.IGNORECASE),
    "how_to": re.compile(r"\b(how to|how do i|how can i|step by step)\b", re.IGNORECASE),
    "definition": re.compile(r"\b(what is|what are|explain|overview|introduction)\b", re.IGNORECASE),
}
CODE_REQUEST_PATTERNS = (
    "give me code",
    "show me code",
    "yaml",
    "show yaml",
    "give yaml",
    "manifest",
    "snippet",
    "code example",
    "example yaml",
    "install command",
    "kubectl",
    "helm",
    "kustomize",
)


def split_terms(value: str) -> List[str]:
    """Split free text, paths, and identifiers into normalized terms."""
    expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    normalized = re.sub(r"[^A-Za-z0-9]+", " ", expanded)
    return [token.lower() for token in normalized.split() if token]


def unique_terms(values: Iterable[str], limit: int = 32) -> List[str]:
    """Return unique normalized terms while preserving order."""
    seen = set()
    ordered: List[str] = []
    for value in values:
        for token in split_terms(str(value)):
            if token not in seen:
                seen.add(token)
                ordered.append(token)
                if len(ordered) >= limit:
                    return ordered
    return ordered


def source_alias_terms(source: str) -> List[str]:
    """Return semantic alias terms for a source path or URL."""
    normalized = source.replace("\\", "/").lower()
    aliases: List[str] = []
    for prefix, hints in PATH_ALIAS_HINTS.items():
        if prefix in normalized:
            aliases.extend(hints)
    return unique_terms(aliases, limit=20)


def analyze_query(question: str) -> Dict[str, object]:
    """Analyze a user question and produce retrieval hints."""
    lowered = question.lower()
    expanded_terms = [question]

    for trigger, additions in QUERY_EXPANSIONS.items():
        if trigger in lowered:
            expanded_terms.extend(additions)

    question_terms = set(split_terms(question))
    query_type = "general"
    for candidate_type, pattern in QUERY_TYPE_PATTERNS.items():
        if pattern.search(question):
            query_type = candidate_type
            break

    wants_code_examples = any(pattern in lowered for pattern in CODE_REQUEST_PATTERNS)
    wants_steps = "step by step" in lowered or query_type in {"install", "how_to"}
    wants_commands = bool(COMMAND_PATTERNS := {"kubectl", "helm", "kustomize", "curl", "docker"} & question_terms)

    prefer_code = bool(question_terms & CODE_INTENT_TERMS) or wants_code_examples or wants_commands
    strongly_prefer_code = bool(
        question_terms & STRONG_CODE_TERMS
    ) or any(term in lowered for term in STRONG_CODE_TERMS)
    prefer_docs = bool(question_terms & DOCS_INTENT_TERMS) or query_type in {
        "definition",
        "install",
        "how_to",
        "compare",
    }

    priority_terms = unique_terms(expanded_terms, limit=28)
    enhanced_query = question
    if len(priority_terms) > len(split_terms(question)):
        enhanced_query = (
            f"{question}\n"
            f"Relevant retrieval hints: {' '.join(priority_terms)}"
        )

    return {
        "question": question,
        "enhanced_query": enhanced_query,
        "priority_terms": priority_terms,
        "query_type": query_type,
        "wants_code_examples": wants_code_examples,
        "wants_steps": wants_steps,
        "wants_commands": wants_commands,
        "prefer_code": prefer_code,
        "strongly_prefer_code": strongly_prefer_code,
        "prefer_docs": prefer_docs,
    }


def lexical_candidate_scores(
    hits: List[Dict[str, object]],
    query_terms: List[str],
) -> List[float]:
    """Compute a BM25-style lexical score over retrieved candidates."""
    if not hits or not query_terms:
        return [0.0 for _ in hits]

    doc_terms: List[List[str]] = []
    doc_lengths: List[int] = []
    doc_freq: Counter[str] = Counter()

    for hit in hits:
        haystack = " ".join(
            [
                str(hit.get("source_url", "")),
                str(hit.get("file_path", "")),
                str(hit.get("symbol_name", "")),
                str(hit.get("heading", "")),
                str(hit.get("parent_heading", "")),
                str(hit.get("heading_path", "")),
                str(hit.get("chunk_type", "")),
                str(hit.get("chunk_text", "")),
            ]
        )
        terms = split_terms(haystack)
        doc_terms.append(terms)
        doc_lengths.append(max(1, len(terms)))
        for term in set(terms):
            doc_freq[term] += 1

    avg_len = sum(doc_lengths) / max(1, len(doc_lengths))
    k1 = 1.2
    b = 0.75
    total_docs = len(hits)
    scores: List[float] = []

    for terms, doc_len in zip(doc_terms, doc_lengths):
        tf = Counter(terms)
        score = 0.0
        for term in query_terms:
            freq = tf.get(term, 0)
            if freq == 0:
                continue
            df = doc_freq.get(term, 0)
            idf = math.log(1 + (total_docs - df + 0.5) / (df + 0.5))
            numerator = freq * (k1 + 1)
            denominator = freq + k1 * (1 - b + b * (doc_len / avg_len))
            score += idf * (numerator / denominator)
        scores.append(score)

    max_score = max(scores) if scores else 0.0
    if max_score <= 0:
        return [0.0 for _ in scores]
    return [score / max_score for score in scores]


def rerank_hits(
    hits: List[Dict[str, object]],
    query_analysis: Dict[str, object],
    top_k: int,
) -> List[Dict[str, object]]:
    """Rerank candidate hits with lightweight hybrid-retrieval heuristics."""
    priority_terms_list = list(query_analysis.get("priority_terms", []))
    priority_terms = set(priority_terms_list)
    prefer_code = bool(query_analysis.get("prefer_code"))
    strongly_prefer_code = bool(query_analysis.get("strongly_prefer_code"))
    prefer_docs = bool(query_analysis.get("prefer_docs"))
    question_lower = str(query_analysis.get("question", "")).lower()
    query_type = str(query_analysis.get("query_type", "general"))
    wants_code_examples = bool(query_analysis.get("wants_code_examples"))
    wants_steps = bool(query_analysis.get("wants_steps"))
    wants_commands = bool(query_analysis.get("wants_commands"))

    reranked: List[Dict[str, object]] = []
    lexical_scores = lexical_candidate_scores(hits, priority_terms_list)

    for hit, lexical_score in zip(hits, lexical_scores):
        score = float(hit.get("distance", 0.0))
        collection = str(hit.get("collection", ""))
        source = str(hit.get("source_url") or hit.get("file_path") or "")
        symbol_name = str(hit.get("symbol_name", ""))
        heading = str(hit.get("heading", ""))
        parent_heading = str(hit.get("parent_heading", ""))
        text = str(hit.get("chunk_text", ""))
        chunk_type = str(hit.get("chunk_type", ""))

        haystack = " ".join([source, symbol_name, heading, parent_heading, chunk_type, text]).lower()
        haystack_terms = set(split_terms(haystack))
        path_aliases = set(source_alias_terms(source))

        # --- Collection preference ---
        if strongly_prefer_code:
            # Strongly boost code results when query mentions specific K8s resources
            if collection == "code_collection":
                score += 0.15
            elif collection == "docs_collection":
                score -= 0.06
        elif prefer_code:
            if collection == "code_collection":
                score += 0.08
            elif collection == "docs_collection":
                score -= 0.03

        if prefer_docs:
            if collection == "docs_collection":
                score += 0.09
            elif collection == "code_collection":
                score -= 0.04

        # --- Term-overlap scoring ---
        term_overlap = len(priority_terms & haystack_terms)
        alias_overlap = len(priority_terms & path_aliases)
        score += min(0.16, 0.014 * term_overlap)
        score += min(0.10, 0.025 * alias_overlap)
        score += 0.24 * lexical_score

        # --- Chunk-type preference ---
        if collection == "docs_collection":
            if query_type == "definition" and chunk_type in {"concept", "faq"}:
                score += 0.08
            if wants_steps and chunk_type == "procedure":
                score += 0.12
            if wants_commands and chunk_type == "command":
                score += 0.14
        if collection == "code_collection":
            if wants_code_examples and chunk_type in {"manifest", "symbol"}:
                score += 0.14
            if wants_commands and chunk_type == "manifest":
                score += 0.12

        # --- Path-keyword boosting ---
        # Extract meaningful keywords from the query and boost hits whose
        # file_path or source_url directly contain those keywords.
        source_lower = source.lower()
        path_keywords = [
            "cache", "metadata", "rbac", "authorization", "runtimes",
            "catalog", "pvcviewer", "release", "webhook", "training-operator",
            "trainer", "kserve", "pipeline", "model-registry",
        ]
        for kw in path_keywords:
            if kw in question_lower and kw in source_lower:
                score += 0.06

        if query_type == "install" and (
            "install" in source_lower or "install" in heading.lower() or "getting started" in heading.lower()
        ):
            score += 0.10
        if query_type == "compare" and "overview" in heading.lower():
            score += 0.04

        if prefer_code and source.endswith((".yaml", ".yml")):
            score += 0.02
        if "kustomization.yaml" in source:
            score += 0.02

        reranked_hit = dict(hit)
        reranked_hit["rerank_score"] = score
        reranked.append(reranked_hit)

    reranked.sort(key=lambda item: item.get("rerank_score", item.get("distance", 0.0)), reverse=True)
    return reranked[:top_k]
