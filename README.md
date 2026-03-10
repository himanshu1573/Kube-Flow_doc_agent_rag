# Kubeflow Docs Agent RAG

This is a fresh, minimal Kubeflow-focused project for a simple documentation RAG system.

It does one thing well:

1. Read Kubeflow documentation files from a mounted directory.
2. Clean and chunk the documents.
3. Create embeddings.
4. Store the chunks and vectors in Milvus using a Kubeflow Pipeline.

It is intentionally not a full agentic system. There is no LangGraph, no routing, and no multi-source retrieval in this version.

It now includes:

- a Kubeflow Pipeline for indexing docs into Milvus
- a FastAPI service for retrieval and simple chat
- Kubernetes manifests for deploying the API
- Helm values for installing Milvus

## Project Layout

- `pipelines/kubeflow_rag_pipeline.py`: main KFP pipeline
- `server/app.py`: minimal retrieval and chat API
- `server/Dockerfile`: API container image
- `k8s/`: Kubernetes manifests and Milvus Helm values
- `requirements.txt`: local dependencies to compile the pipeline
- `server/requirements.txt`: API dependencies
- `DEPLOYMENT_GUIDE.md`: cluster and deployment steps
- `CLUSTER_SETUP.md`: cluster creation guidance

## What You Need

To run this on Kubeflow, you need:

- A Kubernetes cluster with Kubeflow Pipelines installed
- A Milvus service reachable from the cluster
- A directory or volume containing Kubeflow docs in `.md` or `.html`
- Permission to run pipeline components that install Python packages

## Pipeline Stages

The pipeline has three stages:

1. `collect_docs`
   - walks a docs directory
   - reads markdown and HTML files
   - strips HTML into text
   - writes normalized records to a dataset artifact

2. `chunk_and_embed`
   - splits documents into chunks
   - creates embeddings with `sentence-transformers/all-MiniLM-L6-v2`
   - writes chunk records and vectors to a dataset artifact

3. `upsert_to_milvus`
   - connects to Milvus
   - creates the collection if needed
   - inserts chunk records into the target collection

## Local Compilation

Install dependencies:

```bash
pip install -r requirements.txt
```

Compile the pipeline:

```bash
python pipelines/kubeflow_rag_pipeline.py
```

This will generate:

```text
pipelines/kubeflow_rag_pipeline.yaml
```

## Chunk A PDF Locally

If your source is a PDF like [Kubeflow_Documentation.pdf](/Users/himanshup/gsoc_agents/kubeflow-docs-agent-rag/Kubeflow_Documentation.pdf), you can chunk it locally first:

```bash
python scripts/chunk_pdf.py Kubeflow_Documentation.pdf
```

This writes JSONL chunks to:

```text
chunks/kubeflow_documentation_chunks.jsonl
```

You can also tune chunking:

```bash
python scripts/chunk_pdf.py Kubeflow_Documentation.pdf --chunk-size 1200 --chunk-overlap 150
```

## Suggested Runtime Parameters

- `docs_path`: mounted path containing Kubeflow docs
- `docs_path` can also be a single PDF file path
- `milvus_uri`: Milvus endpoint, for example `http://milvus.docs-agent.svc.cluster.local:19530`
- `collection_name`: target Milvus collection
- `chunk_size`: default `1000`
- `chunk_overlap`: default `100`
- `drop_existing`: `true` for a full rebuild, `false` for incremental adds

## Minimal Deployment Flow

1. Deploy Milvus in your Kubeflow namespace.
2. Build and deploy the FastAPI app in `server/`.
3. Make the docs available to the pipeline through a PVC or mounted volume.
4. Compile this pipeline to YAML.
5. Upload the compiled YAML in Kubeflow Pipelines.
6. Run the pipeline with your docs path and Milvus URI.
7. Query the API after indexing finishes.

## Scope

This project is for a simple deployable RAG baseline only. It is the right starting point before building:

- KServe model serving
- citations UI
- agentic routing
- GitHub issue retrieval
