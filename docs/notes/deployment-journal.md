# Deployment & Environment Setup Journal

This document tracks our progress in setting up the development environment and deploying the `docs-agent` prototype to GCP.

## Current Phase: Phase 0 - Environment Preparation
**Goal**: Ensure all required CLI tools (`gcloud`, `kubectl`, `helm`, `docker`) are installed and configured.

---

### [2026-04-14] Starting the Journey

#### 1. Project Identification
- **Project Name**: `KubeFlow-prototype`
- **Project ID**: `<PROJECT_ID>`
- **Region**: `asia-south1`

#### 2. Hardware/OS Context
- **OS**: macOS (Apple Silicon detected via `/opt/homebrew`)
- **Base Tools**: Homebrew is installed at `/opt/homebrew/bin/brew`.

#### 3. Action: Verifying Toolchain & Env Setup
- [x] **Homebrew**: Detected at `/opt/homebrew/bin/brew`.
- [x] **kubectl**: Detected at `/opt/homebrew/bin/kubectl`.
- [x] **helm**: Detected at `/opt/homebrew/bin/helm`.
- [x] **google-cloud-sdk**: INSTALLED (Version 564.0.0).
- [x] **docker**: RUNNING (User started Docker Desktop).

---

### [2026-04-15] Deploying the Prototype

#### 1. Cluster Setup (In Progress)
- **Project ID**: `<PROJECT_ID>`
- **Cluster Name**: `docs-agent-cluster`
- **Region**: `asia-south1`
- **Status**: `PROVISIONING`

#### 2. Infrastructure Preparation
- [x] GKE API Enabled
- [x] Artifact Registry API Enabled
- [x] Cloud Build API Enabled
- [x] Artifact Registry `docs-agent` created in `asia-south1`.

#### 3. Image Building (In Progress)
- [ ] **API Image**: `docker build` in progress.
- [ ] **MCP Image**: Pending API image completion.

#### 4. Kubernetes Configuration
- [ ] Namespace `docs-agent` created. (Waiting for cluster)
- [ ] Milvus installed via Helm. (Waiting for cluster)
