# Agentic RAG on Kubeflow: Working Guide

This guide captures the current project context for `docs-agent`, what is already working, what is still pending, and how to run or deploy the current Phase 1 ingestion stack.

It is meant to be a practical project handoff document, not just a design note.

## 1. Project Context

The broader GSoC goal is to evolve `kubeflow/docs-agent` into a modular, production-grade Agentic RAG reference architecture on Kubeflow.

The target system is split into four layers:

1. Frontend
2. Agent or router layer
3. Ingestion pipelines
4. Vector database backend

At this stage, the strongest and most complete part of the project is the ingestion and vector indexing foundation, which maps to **Phase 1**.

## 2. What Is Done Right Now

### Phase 1 Status

Phase 1 is now in a much better state than before and has a real modular source layout.

Currently implemented:

- A modular docs ingestion source tree under `pipelines/docs_ingestion/`
- A modular code ingestion source tree under `pipelines/code_ingestion/`
- Shared embedding and Milvus helpers under `pipelines/shared/`
- Separate backend schemas for:
  - `docs_collection`
  - `code_collection`
- A combined full-ingestion composition path that can run both docs and code ingestion
- Lightweight Phase 1 tests for basic ingestion contracts

### Specifically Added or Hardened

- `pipelines/docs_ingestion/pipeline.py`
- `pipelines/docs_ingestion/components/crawler.py`
- `pipelines/docs_ingestion/components/chunker.py`
- `pipelines/docs_ingestion/components/embedder.py`
- `pipelines/docs_ingestion/components/loader.py`
- `tests/test_phase1_ingestion.py`

### What This Means

We now have a source-backed docs ingestion implementation that:

- crawls `kubeflow.org/docs`
- extracts page content
- chunks the content into retrieval-ready records
- embeds those chunks
- writes them into Milvus under `docs_collection`

The code ingestion implementation already supports:

- cloning `kubeflow/manifests`
- parsing code and manifests
- chunking with retrieval context
- embedding those chunks
- writing them into Milvus under `code_collection`

## 3. What Has Been Verified

The following has been verified locally:

- Python syntax checks on the new docs ingestion files
- lightweight Phase 1 unit tests
- KFP compile for:
  - docs ingestion pipeline
  - combined full-ingestion pipeline

This gives us confidence that the ingestion architecture is now source-complete and internally consistent enough to use as the Phase 1 base.

## 4. What Is Still Pending

Even after hardening Phase 1, the project is **not yet fully complete end-to-end**.

### Pending in Phase 1

- Run a full live crawl against `kubeflow.org`
- Load real vectors into a live Milvus instance
- Validate collection sizes and retrieval quality with real data
- Submit or run the pipelines in an actual cluster environment if we want true Kubeflow-native execution
- Add stronger evaluation and smoke tests around retrieval quality

### Pending in Phase 2

Phase 2 is now largely implemented in source, but it is not yet fully deployment-verified on a live cluster.

Still missing or not fully wired:

- live end-to-end verification against a populated Milvus instance with both `docs_collection` and `code_collection`
- real image builds and cluster deployment validation for the new shared `agent/` package layout
- production auth, rate limiting, and observability
- evaluation runs on real queries to measure router quality and groundedness

## 5. Current Architecture State

### Good Right Now

- Modular ingestion code exists
- Shared Milvus and embedding helpers exist
- Schemas for docs and code are separated cleanly
- Full-ingestion composition exists
- The project direction is aligned with good engineering practice

### Not Good Enough Yet

- Runtime serving layer now has routing, shared retrieval, and threaded state, but still needs live deployment validation
- Deployment manifests are stronger now, but still need placeholder replacement and real cluster rollout testing
- Real cluster deployment verification for the new Phase 1 path is still pending
- Retrieval quality should be benchmarked on real indexed data

## 6. What You Need From Your Side

To complete the next operational step, you need to decide whether you want to run Phase 1:

1. Locally, without a Kubernetes cluster
2. On a real Kubernetes cluster

### If You Have a Cluster

You need:

- `kubectl`
- `helm`
- access to a Kubernetes cluster
- a namespace where you can deploy Milvus
- ideally Kubeflow Pipelines installed if you want to run the pipelines as actual KFP jobs

### If You Do Not Have a Cluster

You can still validate Phase 1 end-to-end using:

- local Python
- local or Docker-based Milvus
- internet access

This is enough to:

- crawl docs
- embed content
- load vectors
- validate collections

## 7. Recommended Execution Order

If your goal is practical progress today, use this order:

1. Start Milvus
2. Run docs ingestion
3. Run code ingestion
4. Verify `docs_collection` and `code_collection`
5. Test retrieval quality
6. Then move to full cluster deployment

This is safer than trying to deploy everything before validating the vector backend content.

## 8. Commands: Cluster Path

Assume:

- namespace: `docs-agent`
- repo path: `<repo-root>`

### 8.1 Create Namespace and Install Milvus

```bash
export NS=docs-agent

kubectl create namespace "${NS}" --dry-run=client -o yaml | kubectl apply -f -

kubectl get sc

helm repo add zilliztech https://zilliztech.github.io/milvus-helm
helm repo update

helm upgrade --install milvus zilliztech/milvus \
  --namespace "${NS}" \
  --set cluster.enabled=false \
  --set standalone.enabled=true \
  --set etcd.replicaCount=1 \
  --set minio.mode=standalone \
  --set pulsar.enabled=false

kubectl get pods -n "${NS}" -w
```

### 8.2 Port Forward Milvus

Keep this terminal open:

```bash
export NS=docs-agent
kubectl port-forward -n "${NS}" service/milvus-milvus 19530:19530
```

If that service name is different:

```bash
kubectl get svc -n "${NS}"
```

### 8.3 Prepare Python Environment

```bash
cd <repo-root>

python3 -m venv .phase1-venv
source .phase1-venv/bin/activate

pip install --upgrade pip
pip install -r pipelines/requirements.txt
```

### 8.4 Run Live Docs Crawl and Load `docs_collection`

```bash
cd <repo-root>
source .phase1-venv/bin/activate

export PYTHONPATH=<repo-root>
export MILVUS_HOST=127.0.0.1
export MILVUS_PORT=19530
export EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
export MILVUS_DROP_EXISTING_DOCS=true

python - <<'PY'
from pipelines.docs_ingestion.components.crawler import crawl_docs
from pipelines.docs_ingestion.components.chunker import chunk_pages
from pipelines.docs_ingestion.components.embedder import embed_docs_chunks
from pipelines.docs_ingestion.components.loader import load_to_milvus

pages = crawl_docs(
    base_url="https://www.kubeflow.org",
    crawl_delay=0.1,
    max_pages=0,
)
print(f"pages={len(pages)}")

chunks = chunk_pages(
    pages,
    chunk_size=500,
    chunk_overlap=50,
)
print(f"chunks={len(chunks)}")

embedded = embed_docs_chunks(chunks)
summary = load_to_milvus(embedded, collection_name="docs_collection")
print(summary)
PY
```

### 8.5 Run Code Ingestion and Load `code_collection`

```bash
cd <repo-root>
source .phase1-venv/bin/activate

export PYTHONPATH=<repo-root>
export MILVUS_HOST=127.0.0.1
export MILVUS_PORT=19530
export EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
export MILVUS_DROP_EXISTING=true

python - <<'PY'
import shutil

from pipelines.code_ingestion.components.repo_cloner import clone_repo
from pipelines.code_ingestion.components.ast_parser import parse_all_files
from pipelines.code_ingestion.components.chunker import process_chunks
from pipelines.code_ingestion.components.embedder import embed_code_chunks
from pipelines.code_ingestion.components.loader import load_to_milvus

result = clone_repo(
    repo_url="https://github.com/kubeflow/manifests",
    branch="master",
)

try:
    raw_chunks = parse_all_files(
        result["repo_dir"],
        result["file_list"],
        result["commit_sha"],
    )
    print(f"raw_chunks={len(raw_chunks)}")

    processed = process_chunks(raw_chunks)
    print(f"processed_chunks={len(processed)}")

    embedded = embed_code_chunks(processed)
    summary = load_to_milvus(embedded, collection_name="code_collection")
    print(summary)
finally:
    shutil.rmtree(result["repo_dir"], ignore_errors=True)
PY
```

### 8.6 Verify Collections

```bash
cd <repo-root>
source .phase1-venv/bin/activate

export PYTHONPATH=<repo-root>
export MILVUS_HOST=127.0.0.1
export MILVUS_PORT=19530

python - <<'PY'
from pymilvus import connections, utility, Collection

connections.connect(alias="default", host="127.0.0.1", port="19530")

for name in ["docs_collection", "code_collection"]:
    exists = utility.has_collection(name)
    print(name, "exists=", exists)
    if exists:
        col = Collection(name)
        col.load()
        print(name, "num_entities=", col.num_entities)
PY
```

### 8.7 Compile KFP Artifacts

```bash
cd <repo-root>
source .phase1-venv/bin/activate

export PYTHONPATH=<repo-root>

python <repo-root>/pipelines/docs_ingestion/pipeline.py
python <repo-root>/pipelines/code_ingestion/pipeline.py
```

## 9. Commands: No-Cluster Local Validation Path

If you do not have a cluster yet, use local Milvus first.

### 9.1 Start Milvus in Docker

```bash
docker run -d --name milvus-standalone \
  -p 19530:19530 \
  -p 9091:9091 \
  milvusdb/milvus:v2.4.6 \
  milvus run standalone
```

Then use:

```bash
export MILVUS_HOST=127.0.0.1
export MILVUS_PORT=19530
```

After that, run the same docs and code ingestion commands shown above.

## 10. What Can Be Done Next To Improve It

To make the project better, more production-ready, and closer to the final GSoC architecture, the next improvements should be:

### Phase 1 Improvements

- add retrieval smoke tests on real Milvus data
- add dataset size and ingestion summary reporting
- add deduplication and crawl filtering improvements
- add CI checks for pipeline compilation
- add one command or Make target for full Phase 1 bootstrap

### Phase 2 Improvements

- run a full Phase 2 smoke test with populated docs and code collections
- add offline evaluation for intent routing and retrieval grounding
- persist conversation state in Redis or PostgreSQL instead of in-memory storage
- add guardrails, auth, quotas, and tracing around the new API and MCP surfaces
- convert the blueprint manifests into environment-specific Helm templates

### Production Improvements

- stronger observability
- proper auth and rate limiting
- evaluation dataset generation
- feedback loop capture
- safer deployment defaults

## 11. Practical Summary

Right now, the project is strongest in **Phase 1 ingestion and indexing**.

What is ready enough to use:

- docs ingestion source
- code ingestion source
- shared schema and backend helpers
- full-ingestion pipeline composition

What still needs more work before calling the whole system production-grade:

- cluster deployment verification for the new API and MCP images
- retrieval and routing evaluation on real indexed data
- production security, auth, observability, and quota controls

If the immediate goal is progress, the right next step is:

1. run Milvus
2. ingest docs
3. ingest code
4. verify collections
5. build and deploy the new Phase 2 API and MCP images
6. run live routed queries against docs and code collections
