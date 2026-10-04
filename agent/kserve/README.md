# Phase 2 KServe Blueprints

This directory contains baseline deployment blueprints for the Phase 2
agentic RAG architecture.

Components:
- `llm-servingruntime.yaml`: KServe runtime for an OpenAI-compatible LLM backend.
- `llm-inferenceservice.yaml`: KServe `InferenceService` with tool-calling enabled.
- `agent-api-deployment.yaml`: HTTP agent API deployment that performs routing and
  retrieval against Milvus.

Deployment order:
1. Deploy Milvus and load `docs_collection` and `code_collection`.
2. Apply `llm-servingruntime.yaml`.
3. Apply `llm-inferenceservice.yaml`.
4. Build and deploy the `server-https` image with `agent-api-deployment.yaml`.

Notes:
- Replace placeholder image references and namespaces before applying.
- The API deployment expects both Phase 1 collections to exist in Milvus.
- `THREAD_TTL_SECONDS` and `THREAD_MAX_MESSAGES` control the in-memory
  stateful chat window for the HTTP API.
