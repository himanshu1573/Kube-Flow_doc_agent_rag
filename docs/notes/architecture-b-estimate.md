# Architecture B Estimate and Mentor Framing

This note summarizes the realistic implementation effort, resource usage, and the best way to explain the current prototype in relation to **Architecture B (Kagent)**.

## Short Answer

From the current state of the repo, a fully demoable **Architecture B-aligned prototype** is realistically a:

- **4-6 day effort** for a mentor demo
- **7-9 day effort** for a cleaner real Kagent-based prototype
- **10-12 day effort** only if auth, Istio hardening, UI polish, and deployment buffer are all included

Architecture B is **manageable on Google Cloud** if the LLM is kept **external**.
It becomes **heavy** if you also try to run **KServe + local GPU LLM inference** inside the cluster.

## What Is Already Done In Code

The repo already contains major Phase 2 building blocks:

- Semantic routing in [agent/core/router.py](../../agent/core/router.py)
- Shared retrieval in [agent/core/retriever.py](../../agent/core/retriever.py)
- In-memory thread state in [agent/core/state.py](../../agent/core/state.py)
- HTTP API in [server-https/app.py](../../server-https/app.py)
- MCP server in [kagent-feast-mcp/mcp-server/server.py](../../kagent-feast-mcp/mcp-server/server.py)
- Kagent resource setup in [kagent-feast-mcp/manifests/kagent/setup.yaml](../../kagent-feast-mcp/manifests/kagent/setup.yaml)

This means Architecture B is **not starting from zero**. The core routing and tool structure are already present.

## Realistic Time Estimate

### 1. Demoable Architecture B-aligned prototype: 4-6 days

This assumes:

- Milvus is already running or can be brought up quickly
- `docs_collection` and `code_collection` are populated
- Groq or another OpenAI-compatible external LLM is used
- Kagent is integrated at a prototype level, not fully production hardened

Breakdown:

- **1 day**: verify/populate Milvus collections and validate retrieval
- **1 day**: build and deploy API + MCP images
- **1-2 days**: install and wire Kagent resources and debug connectivity
- **1 day**: presentation cleanup, prompt polish, demo readiness
- **0-1 day**: deployment/debugging buffer

### 2. Cleaner Kagent-based prototype: 7-9 days

This includes:

- more stable deployment verification
- better MCP/Kagent validation
- cleaner resource tuning
- basic auth or token protection
- more polished mentor-facing demo behavior

### 3. More complete Architecture B implementation: 10-12 days

This is only realistic if you also include:

- auth
- Istio policy setup
- better UI feedback flow
- stronger observability
- more robust deployment retries and troubleshooting time

## Resource Estimate

## Minimum Practical Resource Budget

For a prototype where the LLM stays **outside** the cluster:

- **API pod**: about `0.5 vCPU / 1Gi RAM` request, up to `2 vCPU / 4Gi RAM`
- **MCP pod**: about `0.5 vCPU / 1Gi RAM` request, up to `1 vCPU / 2Gi RAM`
- **Milvus standalone + etcd + MinIO**: about `1-2 vCPU` and `4-6Gi RAM`
- **Kagent controller/UI**: about `0.5-1 vCPU` and `1-2Gi RAM`

Safe practical cluster budget:

- **3-5 vCPU**
- **7-10Gi RAM**

Comfortable budget with some buffer:

- **4-6 vCPU**
- **10-12Gi RAM**

## If KServe LLM Is Added

If you try to run **Llama 3.1-8B** in-cluster with KServe, the cost rises sharply.

From the existing manifests:

- **GPU**: `1`
- **CPU**: `4-6 vCPU`
- **Memory**: `16-24Gi RAM`

That is the part that makes the stack heavy.

## Is It Huge for Google Cloud?

### With external LLM

**No, it is manageable.**

If you use:

- GKE
- Milvus in-cluster
- API in-cluster
- MCP in-cluster
- Groq or another external OpenAI-compatible LLM

then the architecture is reasonable for a prototype.

### With in-cluster KServe LLM

**Yes, it becomes heavy for a student prototype.**

The biggest cost is not the routing logic.
The biggest cost is:

- GPU requirement
- KServe overhead
- higher memory demand
- more operational debugging

## Honest Technical Conclusion

The right conclusion for this project is:

> The core logic is already aligned with Architecture B, but the full managed deployment has been intentionally optimized for prototype constraints. The Kagent-compatible routing, retrieval, and MCP tool structure already exist in code. For the demo, the LLM is kept external and the cluster footprint is minimized so the system stays reliable and within practical GCP resource limits.

## Best Way To Explain It To A Mentor

You can say:

> The project is architected toward Architecture B using a Kagent-compatible design. The core routing layer, retrieval layer, and MCP tools are already implemented in code. For the prototype, I chose a resource-optimized deployment shape by keeping the LLM external and minimizing cluster-side management overhead. This lets me demonstrate the real agent workflow, retrieval, and Kubernetes deployment behavior without spending most of the budget on GPU inference and control-plane overhead.

## Very Short 30-Second Version

You can say:

> The prototype is Architecture B-aligned in code, but not fully architecture-heavy in deployment. I already implemented the routing, shared retrieval, MCP tools, and Kagent resource definitions. For the demo, I kept the LLM outside the cluster and reduced the Kubernetes overhead so the prototype stays reliable and affordable on GCP. Once more resources are available, the remaining managed Architecture B pieces can be enabled without changing the core logic.

## Presentation Table

| Area | Current Prototype | Full Architecture B Target | Why |
| --- | --- | --- | --- |
| Routing | Implemented | Implemented | Already present in Phase 2 code |
| Retrieval | Implemented | Implemented | Shared Milvus-based retriever exists |
| MCP tools | Implemented | Implemented | MCP server already exposes docs/code/context tools |
| Kagent CRDs | Blueprint and setup present | Full managed runtime | Needs final live integration and validation |
| LLM hosting | External provider like Groq | Could be external or KServe | External is cheaper and easier for demo |
| Auth | Minimal / deferred | Required later | Deferred to save time and resources |
| Istio hardening | Deferred | Optional hardening layer | Useful later, not required for demo |
| Session persistence | In-memory | Redis/Postgres later | Current prototype is enough for demo |

## Final Recommendation

For this project, the best practical path is:

1. Show the current prototype as **Architecture B-ready**
2. Be explicit that the **deployment is resource-optimized**
3. Keep the LLM **external**
4. Avoid claiming that the full managed stack is already production-grade
5. Present the remaining Kagent/operator/auth work as the next milestone, not a missing foundation

## One-Line Summary

**Architecture B is manageable on Google Cloud for this project if the LLM stays external; the full in-cluster managed version is heavier, but the current codebase is already close enough that the remaining work is mostly deployment integration and resource tuning, not a ground-up rebuild.**
