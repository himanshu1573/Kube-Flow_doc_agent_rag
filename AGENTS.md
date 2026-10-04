# AGENTS.md

Guidance for AI coding agents (and humans) working in this repository.

**What this is:** an agentic RAG assistant for Kubeflow. Ingestion indexes kubeflow.org docs and
kubeflow/manifests code into Milvus. A FastAPI agent API routes each question to docs, code or both,
calls an OpenAI-compatible LLM with retrieval tools, and streams cited answers to a website widget.
The same retrieval is exposed over MCP for Kagent.

| Read this | For |
|---|---|
| [.agent/runbook.md](.agent/runbook.md) | Run, verify and clean up the local stack, step by step, with expected output |
| [.agent/rules.md](.agent/rules.md) | Rules to follow when changing code: invariants, security, tests, commits |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design: components, data flow, decisions, limitations |
| [README.md](README.md) | User-facing overview, configuration and API |

## Commands

```bash
make setup         # uv venv (Python 3.12) + deps, creates .env
make test          # unit tests; no Milvus or LLM needed. Run before every commit.
make milvus-up     # Milvus in Docker on :19530
make ingest        # docs + code into Milvus (~6 min on CPU)
make api           # agent API on :8000 (reads .env)
make web           # widget previews on :8090
```

Python code imports from the repo root (`agent.core`, `pipelines.shared`, `backend.schemas`). Run
with `PYTHONPATH=<repo root>`; the Makefile does this for you.

## Where things live

- Shared runtime: `agent/core/` (router, retriever, state). Used by `server-https/`, `server/` and the MCP server.
- Main API: `server-https/app.py`. Widget for kubeflow.org: `website/static/js/agent-widget.js`.
- Ingestion: `pipelines/docs_ingestion/`, `pipelines/code_ingestion/`, `pipelines/shared/`. Local runner: `scripts/ingest_local.py`.
- Tests: `tests/` (`unittest`; LLM calls are mocked with `httpx.MockTransport`).

## Five rules that matter most

1. Never commit secrets. `.env` is gitignored; put new settings in `.env.example`.
2. Ingestion and the API must use the same `EMBEDDING_MODEL`.
3. Client API keys (`X-LLM-API-Key`) must never be logged, stored or sent anywhere except `KSERVE_URL`.
4. Every bug fix gets a regression test that fails before the fix.
5. Keep changes small and in the existing style. Prefer extending `agent/core/` over duplicating logic per server.

Full list: [.agent/rules.md](.agent/rules.md).
