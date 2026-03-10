# Cluster Setup

## In Simple Words

You need a Kubernetes cluster first, and then you install Kubeflow on top of that cluster.

Think of it like this:

- Kubernetes cluster = the land
- Kubeflow = the factory you build on that land
- your RAG app = one machine inside the factory

## Which Cluster Should You Create

There are two realistic options.

### Option 1: `kind` for learning

Use `kind` if you want to:

- learn Kubernetes basics
- test YAML files
- test Docker images
- practice service deployment

This is good for learning, but not the best place for a full Kubeflow setup because Kubeflow is heavy.

Official `kind` quick start:

- [kind Quick Start](https://kind.sigs.k8s.io/docs/user/quick-start/)

Basic commands:

```bash
kind create cluster --name kubeflow-rag --wait 5m
kubectl cluster-info --context kind-kubeflow-rag
kubectl get nodes
```

### Option 2: Managed Kubernetes for real Kubeflow

Use a managed cluster if you want to actually run Kubeflow seriously.

Good options:

- GKE
- EKS
- AKS
- OKE

Official Kubeflow installation overview:

- [Installing Kubeflow](https://www.kubeflow.org/docs/started/installing-kubeflow/)

Kubeflow’s install page explains that you can install:

- standalone Kubeflow projects, or
- the full Kubeflow AI reference platform using manifests or distributions

## What I Recommend

If your goal is just to understand deployment:

1. Create a `kind` cluster
2. Deploy Milvus
3. Deploy the API
4. Learn how services and pods work

If your goal is to show a real Kubeflow demo:

1. Create a managed Kubernetes cluster
2. Install Kubeflow Pipelines or Kubeflow platform there
3. Run the pipeline from this project
4. Deploy the API in the same cluster

## Minimum Cluster Checklist

Before deploying this project, make sure your cluster has:

- `kubectl` access working
- enough CPU and memory for Milvus and the API
- storage or a mounted docs path for the pipeline
- internet access for package installs inside pipeline steps, unless you prebuild images

## Practical Advice

For this project, the easiest sensible path is:

1. start with `kind` to learn the deployment flow
2. move to a managed cluster when you are ready to run Kubeflow properly

That avoids spending time debugging full Kubeflow on a tiny local machine.
