# Docs-Agent Working Context

This file is a working reference for humans and AI agents collaborating on
`kubeflow/docs-agent`.

It is not the product spec and it is not only a deployment guide.
It is the continuity file for:
- what we are building
- what has already been done
- why those choices were made
- what is still pending
- how to run, test, and deploy the current state

If a chat resets or a new contributor joins, start here.

## 1. Project Goal

The project goal is to evolve `docs-agent` from a docs-only retrieval script into
a modular Kubeflow-native agentic RAG architecture.

Target outcome:
- Phase 1: reliable ingestion and vector persistence for both docs and code
- Phase 2: a router-driven runtime that can decide whether a question should go
  to documentation retrieval, code retrieval, or both
- Future phases: hardened deployment, observability, auth, feedback loops,
  evaluation, and production operations

## 2. Architecture We Are Following

We are organizing the system around four layers:

1. Frontend
2. Agent or router layer
3. Ingestion pipelines
4. Vector database backend

Current repo focus:
- Phase 1: ingestion and Milvus indexing
- Phase 2: routing, tool calling, MCP integration, and serving blueprints

## 3. Why The Repo Was Restructured

Originally, the repo had useful pieces, but the architecture was not fully
aligned with the GSoC design:
- runtime paths were docs-only
- collection names and schemas were inconsistent
- routing logic existed as heuristics but was not wired into the live API
- agent code was not clearly modularized

We started restructuring to solve those problems.

Why this was necessary:
- industry-standard systems need clear module boundaries
- deployment becomes easier when docs/code retrieval use one shared logic path
- testing becomes easier when routing and retrieval are separated from transport
- KServe, MCP, and Kagent should not all drift into separate implementations

## 4. What Has Been Done

### Phase 1: Ingestion and Foundation

Phase 1 has been substantially completed in source code.

Implemented:
- modular docs ingestion pipeline under [pipelines/docs_ingestion](../../pipelines/docs_ingestion)
- modular code ingestion pipeline under [pipelines/code_ingestion](../../pipelines/code_ingestion)
- shared embedding and Milvus helpers under [pipelines/shared](../../pipelines/shared)
- separate docs and code schema support under [backend/schemas](../../backend/schemas)
- tests for ingestion behavior under [tests/test_phase1_ingestion.py](../../tests/test_phase1_ingestion.py)

Important docs ingestion files:
- [pipeline.py](../../pipelines/docs_ingestion/pipeline.py)
- [crawler.py](../../pipelines/docs_ingestion/components/crawler.py)
- [chunker.py](../../pipelines/docs_ingestion/components/chunker.py)
- [embedder.py](../../pipelines/docs_ingestion/components/embedder.py)
- [loader.py](../../pipelines/docs_ingestion/components/loader.py)

Important Phase 1 fixes already made:
- added the missing docs ingestion source tree
- aligned Phase 1 around `docs_collection` and `code_collection`
- fixed a code chunking bug so oversized chunks are not silently accepted
- made the docs tokenizer path lazy so tests do not fail just by importing
  the chunker without network access

Why these changes were necessary:
- ingestion is the base of the whole system
- bad chunking creates bad retrieval later
- docs and code need separate but compatible indexing paths
- tests should not depend on downloading tokenizers during import

### Phase 2: Core Agent and Routing

Phase 2 is now largely implemented in source code.

Implemented:
- semantic route classification in [router.py](../../agent/core/router.py)
- shared docs/code retrieval in [retriever.py](../../agent/core/retriever.py)
- in-memory thread state for stateful chat in [state.py](../../agent/core/state.py)
- routed HTTP API in [server-https/app.py](../../server-https/app.py)
- routed WebSocket API in [server/app.py](../../server/app.py)
- MCP server exposing docs, code, and auto-routed search in [kagent-feast-mcp/mcp-server/server.py](../../kagent-feast-mcp/mcp-server/server.py)
- tests for router/state behavior:
  - [tests/test_phase2_router.py](../../tests/test_phase2_router.py)
  - [tests/test_phase2_state.py](../../tests/test_phase2_state.py)

Added deployment blueprints:
- KServe blueprints under [agent/kserve](../../agent/kserve)
- Kagent blueprint under [agent/kagent](../../agent/kagent)
- ADK blueprint under [agent/adk](../../agent/adk)

Why these changes were necessary:
- Phase 2 requires the system to distinguish conceptual questions from
  implementation questions
- a docs-only runtime is not enough for Kubeflow developer workflows
- using a shared retriever avoids inconsistent behavior across API and MCP
- basic statefulness is needed for follow-up questions and multi-turn use

## 5. Current Status Summary

### What Is Done Enough In Code

Phase 1:
- source-complete enough for live ingestion runs
- tested locally
- smoke-tested with Docker-backed Milvus

Phase 2:
- source-complete enough for integration testing
- router is wired into live API paths
- MCP server is upgraded to docs/code/hybrid tooling
- deployable blueprints exist for KServe, Kagent, and ADK-oriented flows

### What Is Not Done Yet

Not yet fully completed from the operational side:
- full live crawl against `kubeflow.org` as the final accepted Phase 1 run
- confirmed real `docs_collection` and `code_collection` in your target Milvus
- live cluster deployment verification for the new Phase 2 stack
- end-to-end testing against a real LLM endpoint in cluster

Not yet production-grade:
- no Redis or Postgres-backed persistent conversation state
- no full auth / OAuth / quota enforcement in the new Phase 2 runtime
- no complete tracing and guardrail integration yet
- no formal retrieval and routing eval suite on real production data

## 6. Why In-Memory State Exists Right Now

Current thread state is stored in [state.py](../../agent/core/state.py).

Why we added it:
- Phase 2 required a stateful RAG behavior
- users need follow-up questions to work
- this was the lightest way to prove the behavior quickly

Why it is not final:
- in-memory state disappears if the pod restarts
- it does not scale cleanly across multiple replicas
- it is not durable enough for audit, analytics, or long-lived sessions

What should replace it later:
- Redis for shared fast session memory
- Postgres for persistent threads, feedback, and analytics

## 7. Important Design Choices

### Shared Retrieval Layer

We intentionally moved routing and retrieval into `agent/core`.

Why:
- API runtime and MCP should use the same retrieval logic
- fixes should happen once, not in multiple places
- this reduces schema drift and behavior drift

### Separate Docs And Code Collections

We intentionally keep docs and code separate.

Why:
- docs and code have different structure and retrieval behavior
- code retrieval needs file path, lines, and snippet semantics
- docs retrieval needs page title, section, and source URL semantics
- separate collections help reduce noisy semantic overlap

### Lazy Loading Of Heavy Dependencies

We intentionally moved heavy clients and models toward lazy loading.

Why:
- tests should not fail just from importing a module
- CI becomes faster and more stable
- local development should not require full runtime services to import helpers

## 8. How To Run The Project Locally

### Basic Python Setup

```bash
cd <repo-root>
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r pipelines/requirements.txt
pip install -r server-https/requirements.txt
pip install -r server/requirements.txt
pip install -r kagent-feast-mcp/mcp-server/requirements.txt
```

### Run Tests

```bash
cd <repo-root>
export PYTHONPATH=<repo-root>
python3 -m unittest discover -s tests
```

### Local Milvus With Docker

If you want local validation without a Kubernetes cluster:

```bash
docker run -d --name milvus-standalone \
  -p 19530:19530 \
  -p 9091:9091 \
  milvusdb/milvus:v2.4.6 \
  milvus run standalone
```

Then:

```bash
export MILVUS_HOST=127.0.0.1
export MILVUS_PORT=19530
```

### Run Docs Ingestion Locally

```bash
cd <repo-root>
source .venv/bin/activate
export PYTHONPATH=<repo-root>
export MILVUS_HOST=127.0.0.1
export MILVUS_PORT=19530
export EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
export MILVUS_DROP_EXISTING_DOCS=true

python3 - <<'PY'
from pipelines.docs_ingestion.components.crawler import crawl_docs
from pipelines.docs_ingestion.components.chunker import chunk_pages
from pipelines.docs_ingestion.components.embedder import embed_docs_chunks
from pipelines.docs_ingestion.components.loader import load_to_milvus

pages = crawl_docs(base_url="https://www.kubeflow.org", crawl_delay=0.1, max_pages=5)
chunks = chunk_pages(pages, chunk_size=500, chunk_overlap=50)
embedded = embed_docs_chunks(chunks)
print(load_to_milvus(embedded, collection_name="docs_collection"))
PY
```

### Run Code Ingestion Locally

```bash
cd <repo-root>
source .venv/bin/activate
export PYTHONPATH=<repo-root>
export MILVUS_HOST=127.0.0.1
export MILVUS_PORT=19530
export EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2

python3 - <<'PY'
import shutil
from pipelines.code_ingestion.components.repo_cloner import clone_repo
from pipelines.code_ingestion.components.ast_parser import parse_all_files
from pipelines.code_ingestion.components.chunker import process_chunks
from pipelines.code_ingestion.components.embedder import embed_code_chunks
from pipelines.code_ingestion.components.loader import load_to_milvus

result = clone_repo(repo_url="https://github.com/kubeflow/manifests", branch="master")
try:
    raw_chunks = parse_all_files(result["repo_dir"], result["file_list"], result["commit_sha"])
    processed = process_chunks(raw_chunks)
    embedded = embed_code_chunks(processed)
    print(load_to_milvus(embedded, collection_name="code_collection"))
finally:
    shutil.rmtree(result["repo_dir"], ignore_errors=True)
PY
```

### Verify Collections

```bash
cd <repo-root>
source .venv/bin/activate
export PYTHONPATH=<repo-root>

python3 - <<'PY'
from pymilvus import connections, utility, Collection

connections.connect(alias="default", host="127.0.0.1", port="19530")
for name in ["docs_collection", "code_collection"]:
    print(name, utility.has_collection(name))
    if utility.has_collection(name):
        col = Collection(name)
        col.load()
        print("entities", col.num_entities)
PY
```

### Run The HTTP API Locally

```bash
cd <repo-root>
source .venv/bin/activate
export PYTHONPATH=<repo-root>
export MILVUS_HOST=127.0.0.1
export MILVUS_PORT=19530
export KSERVE_URL=http://<YOUR_LLM_ENDPOINT>/openai/v1/chat/completions
export MODEL=llama3.1-8B

python3 server-https/app.py
```

### Test The HTTP API

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "What is Kubeflow Pipelines?",
    "stream": false
  }'
```

Test a code-oriented question:

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "How do I configure the notebook mutating webhook YAML?",
    "stream": false
  }'
```

Test follow-up with thread state:

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Show me the related YAML path",
    "thread_id": "<THREAD_ID_FROM_PREVIOUS_RESPONSE>",
    "stream": false
  }'
```

## 9. How To Deploy

### Phase 1 Deployment Shape

Minimum Phase 1 deployment:
1. Deploy Milvus
2. Run docs ingestion
3. Run code ingestion
4. Verify `docs_collection` and `code_collection`

### Phase 2 Deployment Shape

Minimum Phase 2 deployment:
1. Ensure Phase 1 collections are already populated
2. Build and push the API image from [server-https/Dockerfile](../../server-https/Dockerfile)
3. Build and push the MCP image from [kagent-feast-mcp/mcp-server/Dockerfile](../../kagent-feast-mcp/mcp-server/Dockerfile)
4. Replace placeholders in manifests
5. Deploy LLM runtime and API
6. Deploy MCP
7. Deploy Kagent resources if using the Kagent path

### Example Build Commands

Run from repo root:

```bash
cd <repo-root>

docker build -f server-https/Dockerfile -t <YOUR_REGISTRY>/kubeflow-agent-api:latest .
docker push <YOUR_REGISTRY>/kubeflow-agent-api:latest

docker build -f kagent-feast-mcp/mcp-server/Dockerfile -t <YOUR_REGISTRY>/mcp-kubeflow-docs:latest .
docker push <YOUR_REGISTRY>/mcp-kubeflow-docs:latest
```

### Example Apply Order

For KServe-style deployment:

```bash
kubectl apply -f agent/kserve/llm-servingruntime.yaml
kubectl apply -f agent/kserve/llm-inferenceservice.yaml
kubectl apply -f agent/kserve/agent-api-deployment.yaml
```

For MCP:

```bash
kubectl apply -f kagent-feast-mcp/manifests/mcp-server/mcp-server.yaml
```

For Kagent:

```bash
kubectl apply -f kagent-feast-mcp/manifests/kagent/setup.yaml
```

Important:
- replace `<YOUR_NAMESPACE>`
- replace image placeholders
- replace model provider placeholders
- confirm Milvus service hostnames match your cluster

## 10. What Is Still Pending

### Phase 1 Pending

- full accepted live ingestion run on real target infrastructure
- real retrieval checks on final indexed data
- stronger noise filtering for docs crawl output

### Phase 2 Pending

- full end-to-end cluster validation
- real LLM integration verification in the deployed environment
- formal router quality testing on a curated evaluation set
- persistent state backend if production-grade durability is required

### Hardening Pending

- auth and quota controls
- observability and tracing
- feedback capture and golden dataset building
- output guardrails
- environment-specific Helm/Terraform packaging

## 11. What To Tell A Mentor Right Now

Suggested status summary:

Phase 1 is mostly complete in source and has been locally smoke-tested, including
docs and code ingestion paths with Milvus-backed validation. Phase 2 is now
implemented in source as a routed agentic RAG runtime with shared docs/code
retrieval, MCP integration, and deployment blueprints for KServe, Kagent, and
ADK-style architectures. The main remaining work is operational: live ingestion,
cluster deployment, end-to-end testing against a real LLM endpoint, and
production hardening such as auth, observability, and persistent session state.

## 12. If A New AI Agent Takes Over

Start by reading these files:
- [CONTEXT.md](project-context.md)
- [guide.md](working-guide.md)
- [agent/core/router.py](../../agent/core/router.py)
- [agent/core/retriever.py](../../agent/core/retriever.py)
- [server-https/app.py](../../server-https/app.py)
- [kagent-feast-mcp/mcp-server/server.py](../../kagent-feast-mcp/mcp-server/server.py)

Then determine which of these is the current priority:
- live ingestion
- local API testing
- cluster deployment
- retrieval quality evaluation
- production hardening

Do not assume the project is fully production-ready just because Phase 2 source
code exists.
