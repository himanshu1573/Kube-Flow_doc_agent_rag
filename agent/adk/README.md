# Phase 2 Google ADK Blueprint

This directory provides a baseline Google ADK-oriented definition for the same
Phase 2 routing architecture.

What it covers:
- explicit docs vs code routing
- reuse of the shared Milvus retrieval layer
- a single entrypoint agent that can be adapted into a more complex multi-agent
  design later

This is a blueprint, not a pinned production runtime yet. Before using it in a
live cluster:
- choose the exact `google-adk` package version
- wire credentials for the selected LLM backend
- add tracing and guardrails consistent with the rest of the deployment
