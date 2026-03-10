# Deployment Guide

## What This Project Includes

This project now has two deployable parts:

1. A Kubeflow Pipeline that indexes docs into Milvus
2. A FastAPI service that searches Milvus and optionally calls an LLM

## What You Still Need In Your Cluster

- Kubernetes cluster
- Kubeflow Pipelines installed
- Milvus installed
- documentation files available to the pipeline
- one container registry for your API image

## Deploy Order

1. Create the cluster
2. Install Kubeflow or use an existing Kubeflow cluster
3. Install Milvus
4. Build and push the API image
5. Apply the API manifests
6. Create the docs PVC and copy the PDF into it
7. Compile and upload the Kubeflow Pipeline
8. Run the pipeline to index docs
9. Query the API

## API Build

From the project root:

```bash
docker build -f server/Dockerfile -t your-dockerhub-username/kubeflow-docs-rag-api:latest .
docker push your-dockerhub-username/kubeflow-docs-rag-api:latest
```

Update the image name in:

- `k8s/api-deployment.yaml`

## Namespace

```bash
kubectl apply -f k8s/namespace.yaml
```

## Install Milvus

```bash
helm repo add milvus https://zilliztech.github.io/milvus-helm/
helm repo update
helm upgrade --install milvus milvus/milvus -n docs-agent -f k8s/milvus-values.yaml
```

Check it:

```bash
kubectl get pods -n docs-agent
kubectl get svc -n docs-agent
```

## Optional LLM Secret

If you want generated answers instead of retrieval-only mode:

```bash
cp k8s/rag-llm-secret.example.yaml k8s/rag-llm-secret.yaml
```

Then edit `k8s/rag-llm-secret.yaml` and replace the example values:

- `llm_provider`
- `gemini_api_key`
- `gemini_model`

Apply it:

```bash
kubectl apply -f k8s/rag-llm-secret.yaml
kubectl rollout restart deployment/kubeflow-docs-rag-api -n docs-agent
kubectl rollout status deployment/kubeflow-docs-rag-api -n docs-agent
```

What you need from your side:

- one Gemini API key if you want to use Gemini directly
- or an OpenAI-compatible endpoint URL, model name, and API key if you prefer another provider

For Gemini 2.5 Flash, the simplest secret values are:

- `llm_provider=gemini`
- `gemini_model=gemini-2.5-flash`
- `gemini_api_key=<your key>`

Edit this file:

- `k8s/rag-llm-secret.yaml`

If you want to use an OpenAI-compatible endpoint instead, keep using:

- `llm_chat_url`
- `llm_model`
- `llm_api_key`

## Deploy API

```bash
kubectl apply -f k8s/api-deployment.yaml
kubectl apply -f k8s/api-service.yaml
```

Check it:

```bash
kubectl get deployment,svc -n docs-agent
kubectl logs deploy/kubeflow-docs-rag-api -n docs-agent
```

## Compile Pipeline

Install local compiler dependency:

```bash
pip install -r requirements.txt
```

Compile:

```bash
python pipelines/kubeflow_rag_pipeline.py
```

This generates:

```text
pipelines/kubeflow_rag_pipeline.yaml
```

## Upload And Run Pipeline

Before running the pipeline, the lightest option for a small PDF is to create a ConfigMap from it:

```bash
kubectl create configmap kubeflow-docs-pdf \
  -n kubeflow \
  --from-file=Kubeflow_Documentation.pdf=/Users/himanshup/gsoc_agents/kubeflow-docs-agent-rag/Kubeflow_Documentation.pdf
```

If you prefer PVC-based storage for larger document sets, keep using:

- `k8s/docs-pvc.yaml`
- `k8s/docs-loader-pod.yaml`
- `k8s/docs-loader-pod-v2.yaml`

In Kubeflow Pipelines UI:

1. Upload `pipelines/kubeflow_rag_pipeline.yaml`
2. Create a run
3. Set:
   - `docs_path`
   - `milvus_uri`
   - `collection_name`
   - `drop_existing`

Example values:

- `docs_path=/data/kubeflow-docs`
- `milvus_uri=http://milvus.docs-agent.svc.cluster.local:19530`
- `collection_name=kubeflow_docs_rag`
- `drop_existing=true`

For your PDF specifically, if it is mounted into the pipeline container at:

```text
/data/Kubeflow_Documentation.pdf
```

use:

- `docs_path=/data/Kubeflow_Documentation.pdf`
- `docs_config_map_name=kubeflow-docs-pdf`
- `milvus_uri=http://milvus.docs-agent.svc.cluster.local:19530`
- `collection_name=kubeflow_pdf_rag`
- `chunk_size=1000`
- `chunk_overlap=100`
- `drop_existing=true`

## Testing The API

Port-forward:

```bash
kubectl port-forward svc/kubeflow-docs-rag-api 8000:80 -n docs-agent
```

UI:

```text
http://localhost:8000
```

Health:

```bash
curl http://localhost:8000/health
```

Search:

```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query":"What is Kubeflow Pipelines?","top_k":3}'
```

Chat:

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"What is Kubeflow Pipelines?","top_k":3}'
```

If no LLM secret is configured, `/chat` returns retrieved context only.

## Cluster Creation Options

### Option 1: Local cluster for learning

Use `kind` or `minikube` if you only want to test Kubernetes basics.

This is fine for:

- learning `kubectl`
- testing simple deployments
- trying the API service

This is usually not the best choice for a full Kubeflow install because Kubeflow is heavy.

### Option 2: Managed cloud cluster for real Kubeflow

Use a managed Kubernetes service if you want to actually run Kubeflow:

- GKE
- EKS
- AKS
- OKE

This is the practical option for Kubeflow.

## Recommended Cluster Path

If your goal is only to learn deployment:

1. Create a `kind` cluster
2. Deploy Milvus and the API
3. Learn the basic flow

If your goal is to run Kubeflow seriously:

1. Create a managed Kubernetes cluster
2. Install Kubeflow
3. Run this project there
