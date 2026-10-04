# Live Architecture B Demo Assets

This folder contains the cleaned-up deployment path for the live `docs-agent`
demo running in GKE.

## What is here

- `mcp/Dockerfile`
  Builds a dedicated MCP image by extending the already-working API image and
  baking `fastmcp` plus the MCP server entrypoint into the image.
- `mcp/cloudbuild.yaml`
  Cloud Build config for producing the dedicated MCP image in Artifact Registry.
- `manifests/docs-agent-mcp.yaml`
  MCP Deployment and Service for the live `docs-agent` namespace.
- `manifests/docs-agent-kagent.yaml`
  Kagent `ModelConfig`, `RemoteMCPServer`, and `Agent` resources for the live
  namespace.

## Build the dedicated MCP image

Run from the repo root:

```bash
gcloud builds submit . \
  --config deploy/live/mcp/cloudbuild.yaml \
  --substitutions=_BASE_IMAGE=asia-south1-docker.pkg.dev/<PROJECT_ID>/docs-agent/kubeflow-agent-api:latest,_IMAGE=asia-south1-docker.pkg.dev/<PROJECT_ID>/docs-agent/mcp-kubeflow-docs:latest
```

## Deploy the dedicated MCP image

```bash
kubectl apply -f deploy/live/manifests/docs-agent-mcp.yaml
kubectl apply -f deploy/live/manifests/docs-agent-kagent.yaml
```

## Demo checks

```bash
kubectl get pods,svc -n docs-agent
kubectl get agents,remotemcpservers,modelconfigs -n docs-agent -o wide
kubectl -n docs-agent port-forward service/kagent-ui 8080:8080
kubectl -n docs-agent port-forward service/kubeflow-rag-agent 8089:8080
curl http://127.0.0.1:8089/.well-known/agent-card.json
```
