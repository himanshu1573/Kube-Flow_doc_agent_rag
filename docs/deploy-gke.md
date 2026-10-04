# GCP Cluster Deployment Guide

This document explains how to deploy the current `docs-agent` prototype on a
real Kubernetes cluster in Google Cloud Platform.

This is meant for a **working prototype** that can be shown to mentors:
- real cluster
- real pod-to-pod communication
- Milvus running inside the cluster
- docs and code indexed into Milvus
- routed API running in-cluster
- optional MCP server running in-cluster

It is **not** the full production deployment guide.
For today, the goal is a working dogfooded prototype with the least moving parts.

## 1. What We Are Deploying

For the prototype, deploy only this path:

1. GKE cluster
2. Milvus inside the cluster
3. Phase 1 docs ingestion into Milvus
4. Phase 1 code ingestion into Milvus
5. Phase 2 routed HTTP API inside the cluster
6. Optional MCP server inside the cluster

Do **not** try to deploy all possible architectures today.

For the prototype, skip:
- in-cluster KServe GPU LLM serving
- full Kagent controller-based flow
- frontend deployment
- auth/rate limiting/quotas
- Redis/Postgres session persistence

## 2. Why This Deployment Shape

This path is chosen because it is:
- enough to prove cluster deployment
- enough to prove pod-to-pod communication
- enough to prove docs/code retrieval and routing
- much cheaper and simpler than trying to run the entire stack in-cluster

You can still show:
- Milvus running in-cluster
- API pod reaching Milvus by service DNS
- routed answers for conceptual questions vs code/config questions
- citations returned from indexed Kubeflow docs/code

## 3. Requirements

Before starting, you need:

### GCP Requirements

- a GCP project with billing enabled
- free trial credits available
- `gcloud` CLI installed
- `kubectl` installed
- `helm` installed
- Docker installed locally

### Project Requirements

- repo checked out locally at:
  - `<repo-root>`
- access to push images to a container registry
- ability to run local Python commands for ingestion

### Runtime Requirements

- one external OpenAI-compatible LLM endpoint for Phase 2 API testing

Examples:
- Groq
- OpenAI-compatible hosted endpoint
- any compatible endpoint that supports `/v1/chat/completions`

For the prototype, this is easier than trying to run the LLM inside GKE.

## 4. What Is Already Done In Code

The current repo already contains:

### Phase 1

- docs ingestion pipeline:
  - [pipelines/docs_ingestion/pipeline.py](../pipelines/docs_ingestion/pipeline.py)
- code ingestion pipeline:
  - [pipelines/code_ingestion/pipeline.py](../pipelines/code_ingestion/pipeline.py)
- Milvus and embedding helpers
- docs and code schemas

### Phase 2

- router:
  - [agent/core/router.py](../agent/core/router.py)
- shared retrieval:
  - [agent/core/retriever.py](../agent/core/retriever.py)
- thread state:
  - [agent/core/state.py](../agent/core/state.py)
- HTTP API:
  - [server-https/app.py](../server-https/app.py)
- MCP server:
  - [kagent-feast-mcp/mcp-server/server.py](../kagent-feast-mcp/mcp-server/server.py)

### Deployment Manifests To Use

For the prototype, use:
- API deployment:
  - [agent/kserve/agent-api-deployment.yaml](../agent/kserve/agent-api-deployment.yaml)
- MCP deployment:
  - [kagent-feast-mcp/manifests/mcp-server/mcp-server.yaml](../kagent-feast-mcp/manifests/mcp-server/mcp-server.yaml)

Avoid using the older deploy files as the main path today:
- [server-https/deployment.yaml](../server-https/deployment.yaml)
- [server/deployment.yaml](../server/deployment.yaml)

## 5. Cost-Safe Prototype Strategy

To keep GCP costs low:

- use a small GKE Autopilot cluster
- deploy only Milvus + API first
- use an external LLM endpoint
- do not use GPU nodes for the prototype
- do not deploy frontend/KServe/Kagent unless necessary
- delete the cluster after the demo if needed

## 6. Step 1: Authenticate To GCP

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
```

Confirm:

```bash
gcloud config get-value project
```

## 7. Step 2: Enable Required Services

```bash
gcloud services enable \
  container.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com
```

These services are required for:
- GKE
- image registry
- image build support

## 8. Step 3: Create Artifact Registry

We need a place to push the API and MCP images.

```bash
gcloud artifacts repositories create docs-agent \
  --repository-format=docker \
  --location=asia-south1 \
  --description="docs-agent prototype images"
```

Then configure Docker auth:

```bash
gcloud auth configure-docker asia-south1-docker.pkg.dev
```

Set helper variables:

```bash
export PROJECT_ID=YOUR_PROJECT_ID
export REGION=asia-south1
export REPO=docs-agent

export API_IMAGE=${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/kubeflow-agent-api:latest
export MCP_IMAGE=${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/mcp-kubeflow-docs:latest
```

## 9. Step 4: Create GKE Cluster

Use GKE Autopilot for the prototype.

```bash
gcloud container clusters create-auto docs-agent-cluster \
  --region asia-south1
```

Connect to the cluster:

```bash
gcloud container clusters get-credentials docs-agent-cluster \
  --region asia-south1
```

Create namespace:

```bash
kubectl create namespace docs-agent
```

Verify cluster access:

```bash
kubectl get nodes
kubectl get ns
```

## 10. Step 5: Install Milvus In-Cluster

Add the Helm repo and install Milvus.

```bash
helm repo add zilliztech https://zilliztech.github.io/milvus-helm
helm repo update

helm upgrade --install milvus zilliztech/milvus \
  -n docs-agent \
  --create-namespace \
  --set cluster.enabled=false \
  --set standalone.enabled=true \
  --set etcd.replicaCount=1 \
  --set minio.mode=standalone \
  --set pulsar.enabled=false
```

Watch pods:

```bash
kubectl get pods -n docs-agent -w
```

Wait until Milvus-related pods are healthy.

List services:

```bash
kubectl get svc -n docs-agent
```

Important:
- note the actual Milvus service name
- do not assume it is always `milvus.docs-agent.svc.cluster.local`
- often it may be something like `milvus-milvus`

Set the Milvus service variable after inspecting services:

```bash
export NS=docs-agent
export MILVUS_SVC=milvus-milvus
```

Replace `milvus-milvus` if your service name is different.

## 11. Step 6: Port-Forward Milvus To Your Laptop

Keep this running in one terminal:

```bash
kubectl port-forward -n ${NS} svc/${MILVUS_SVC} 19530:19530
```

This allows local ingestion scripts to write directly into the cluster Milvus.

## 12. Step 7: Prepare Local Python Environment

In a new terminal:

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

Set environment variables:

```bash
export PYTHONPATH=<repo-root>
export MILVUS_HOST=127.0.0.1
export MILVUS_PORT=19530
export EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
export DOCS_COLLECTION=docs_collection
export LEGACY_DOCS_COLLECTION=docs_rag
export CODE_COLLECTION=code_collection
```

Optional:
- set `HF_TOKEN` if you want faster Hugging Face downloads

## 13. Step 8: Verify Tests Before Deploying

```bash
cd <repo-root>
export PYTHONPATH=<repo-root>
python3 -m unittest discover -s tests
```

Expected result:
- tests pass

## 14. Step 9: Run Docs Ingestion Into Cluster Milvus

```bash
python3 - <<'PY'
from pipelines.docs_ingestion.components.crawler import crawl_docs
from pipelines.docs_ingestion.components.chunker import chunk_pages
from pipelines.docs_ingestion.components.embedder import embed_docs_chunks
from pipelines.docs_ingestion.components.loader import load_to_milvus

pages = crawl_docs(
    base_url="https://www.kubeflow.org",
    crawl_delay=0.1,
    max_pages=20,
)
print("pages:", len(pages))

chunks = chunk_pages(
    pages,
    chunk_size=500,
    chunk_overlap=50,
)
print("chunks:", len(chunks))

embedded = embed_docs_chunks(chunks)
summary = load_to_milvus(embedded, collection_name="docs_collection")
print("docs load summary:", summary)
PY
```

Expected result:
- docs pages crawled
- chunks created
- vectors inserted into `docs_collection`

## 15. Step 10: Run Code Ingestion Into Cluster Milvus

```bash
python3 - <<'PY'
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
    print("raw chunks:", len(raw_chunks))

    processed = process_chunks(raw_chunks)
    print("processed chunks:", len(processed))

    embedded = embed_code_chunks(processed)
    summary = load_to_milvus(embedded, collection_name="code_collection")
    print("code load summary:", summary)
finally:
    shutil.rmtree(result["repo_dir"], ignore_errors=True)
PY
```

Expected result:
- repo cloned
- code chunks created
- vectors inserted into `code_collection`

## 16. Step 11: Verify Milvus Collections

```bash
python3 - <<'PY'
from pymilvus import connections, utility, Collection

connections.connect(alias="default", host="127.0.0.1", port="19530")

for name in ["docs_collection", "code_collection"]:
    exists = utility.has_collection(name)
    print(name, "exists =", exists)
    if exists:
        collection = Collection(name)
        collection.load()
        print(name, "entities =", collection.num_entities)
PY
```

Expected result:
- both collections exist
- both collections have rows

## 17. Step 12: Build And Push API Image

From repo root:

```bash
cd <repo-root>

docker build -f server-https/Dockerfile -t ${API_IMAGE} .
docker push ${API_IMAGE}
```

## 18. Step 13: Build And Push MCP Image

Optional but recommended if you want to show MCP in the prototype:

```bash
docker build -f kagent-feast-mcp/mcp-server/Dockerfile -t ${MCP_IMAGE} .
docker push ${MCP_IMAGE}
```

## 19. Step 14: Choose A Real LLM Endpoint

For the prototype, use an external OpenAI-compatible endpoint.

Set:

```bash
export LLM_URL=https://YOUR_REAL_OPENAI_COMPATIBLE_ENDPOINT/v1/chat/completions
```

Examples:
- Groq OpenAI-compatible API
- any compatible hosted endpoint

Do not use placeholders.

Do not use the default cluster URL from the code unless you really deployed an
in-cluster LLM at that exact hostname.

## 20. Step 15: Create Final API Manifest For Your Cluster

Patch the API blueprint with real values:

```bash
sed \
  -e "s#<YOUR_NAMESPACE>#${NS}#g" \
  -e "s#<YOUR_IMAGE>#${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}#g" \
  -e "s#http://kubeflow-agent-llm.<YOUR_NAMESPACE>.svc.cluster.local/openai/v1/chat/completions#${LLM_URL}#g" \
  -e "s#milvus.<YOUR_NAMESPACE>.svc.cluster.local#${MILVUS_SVC}.${NS}.svc.cluster.local#g" \
  agent/kserve/agent-api-deployment.yaml > /tmp/docs-agent-api.yaml
```

Inspect it:

```bash
cat /tmp/docs-agent-api.yaml
```

Apply it:

```bash
kubectl apply -f /tmp/docs-agent-api.yaml
```

Check pods:

```bash
kubectl get pods -n ${NS}
kubectl logs -n ${NS} deployment/kubeflow-agent-api
```

Expected result:
- API pod starts successfully
- no image pull errors
- no Milvus DNS errors
- no LLM DNS errors

## 21. Step 16: Test API In-Cluster

Port-forward the API:

```bash
kubectl port-forward -n ${NS} svc/kubeflow-agent-api 8000:8000
```

In another terminal, test a conceptual query:

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "What is Kubeflow Pipelines?",
    "stream": false
  }'
```

Test a code/config query:

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "How do I configure the notebook mutating webhook YAML?",
    "stream": false
  }'
```

Expected result:
- first query routes to docs/hybrid
- second query routes to code
- citations are returned

## 22. Step 17: Test Follow-Up Threading

The first non-streaming response should include `thread_id`.

Use that `thread_id` in the next request:

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Show me the related YAML path",
    "thread_id": "PASTE_THREAD_ID_HERE",
    "stream": false
  }'
```

Expected result:
- follow-up works as a multi-turn conversation

## 23. Step 18: Optional MCP Deployment

If API works, deploy MCP.

Patch the MCP manifest:

```bash
sed \
  -e "s#<YOUR_NAMESPACE>#${NS}#g" \
  -e "s#<YOUR_DOCKERHUB_USERNAME>/mcp-kubeflow-docs:latest#${MCP_IMAGE}#g" \
  -e "s#milvus.<YOUR_NAMESPACE>.svc.cluster.local#${MILVUS_SVC}.${NS}.svc.cluster.local#g" \
  kagent-feast-mcp/manifests/mcp-server/mcp-server.yaml > /tmp/docs-agent-mcp.yaml
```

Inspect:

```bash
cat /tmp/docs-agent-mcp.yaml
```

Apply:

```bash
kubectl apply -f /tmp/docs-agent-mcp.yaml
```

Verify:

```bash
kubectl get pods -n ${NS}
kubectl logs -n ${NS} deployment/mcp-kubeflow-docs
```

Expected result:
- MCP pod comes up
- MCP can connect to Milvus

## 24. Step 19: What To Skip For Today

For the prototype, skip:

- [agent/kserve/llm-servingruntime.yaml](../agent/kserve/llm-servingruntime.yaml)
- [agent/kserve/llm-inferenceservice.yaml](../agent/kserve/llm-inferenceservice.yaml)
- [kagent-feast-mcp/manifests/kagent/setup.yaml](../kagent-feast-mcp/manifests/kagent/setup.yaml)

Why skip them for now:
- they add more dependencies
- KServe LLM serving is costlier and slower to get working
- Kagent is not required to prove the core prototype

## 25. Step 20: What Counts As A Successful Prototype

You can say the prototype is working if all of these are true:

- GKE cluster is running
- Milvus is running in-cluster
- `docs_collection` exists and is populated
- `code_collection` exists and is populated
- API pod is running in-cluster
- API pod can reach Milvus by service DNS
- docs query works
- code query works
- citations are returned
- optional MCP server also runs in-cluster

That is enough to demonstrate:
- dogfooding
- pod-to-pod communication
- a real working prototype

## 26. Remaining Work After Prototype

After the prototype is working, the main remaining items are:

### Phase 1 Remaining

- larger ingestion run
- stronger retrieval quality validation
- operational scheduling via real KFP if needed

### Phase 2 Remaining

- in-cluster LLM serving with KServe
- Kagent integration validation
- stronger evaluation of router quality

### Hardening Remaining

- auth
- rate limiting
- tracing
- guardrails
- persistent state backend
- frontend

## 27. Common Problems And Fixes

### Problem: API pod cannot connect to Milvus

Cause:
- wrong Milvus service name in the manifest

Fix:
- run:
  ```bash
  kubectl get svc -n docs-agent
  ```
- update `MILVUS_SVC`
- recreate patched manifest

### Problem: API pod cannot reach the LLM

Cause:
- using placeholder or cluster-only hostname that does not exist

Fix:
- set `LLM_URL` to a real external endpoint
- redeploy API manifest

### Problem: image pull errors

Cause:
- wrong Artifact Registry path
- Docker auth not configured

Fix:
- rerun:
  ```bash
  gcloud auth configure-docker asia-south1-docker.pkg.dev
  ```
- confirm image exists in Artifact Registry

### Problem: ingestion cannot connect to Milvus

Cause:
- port-forward not running
- wrong service name

Fix:
- keep port-forward terminal open
- confirm local `19530` is forwarded to the correct Milvus service

## 28. Suggested Demo Flow

For the mentor demo:

1. show GKE cluster and pods
2. show Milvus running
3. show `docs_collection` and `code_collection` are populated
4. show API pod logs or service
5. send one docs question
6. send one code question
7. show citations in responses
8. optionally show MCP server is up

## 29. Final Notes

This deployment path is intentionally minimal.

It is the right choice when:
- you need a working prototype quickly
- you need a real cluster deployment
- you need pod-to-pod communication
- you want to keep cloud costs low

It is not yet the final production architecture, but it is a valid and strong
prototype path for submission and mentor review.
