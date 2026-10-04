# Kubeflow Agent Showcase Runbook

## Local Demo URLs

- Standalone agent section:
  [agent-section-demo.html](demo/agent-section-demo.html)
- Static local URL:
  [http://127.0.0.1:8090/demo/agent-section-demo.html](http://127.0.0.1:8090/demo/agent-section-demo.html)
- Kagent UI:
  [http://127.0.0.1:8088](http://127.0.0.1:8088)
- Managed agent A2A endpoint:
  [http://127.0.0.1:8089/.well-known/agent-card.json](http://127.0.0.1:8089/.well-known/agent-card.json)

## What Is Already Running

- `kubectl -n docs-agent port-forward service/kubeflow-agent-api 8000:8000`
- `kubectl -n docs-agent port-forward service/kagent-ui 8088:8080`
- `kubectl -n docs-agent port-forward service/kubeflow-rag-agent 8089:8080`
- `python3 -m http.server 8090 -d .`

## Fastest Demo Flow

1. Open the standalone agent section page.
2. Click `Open Live Agent`.
3. Ask:
   `How does the Kubeflow agent decide whether to search docs, code, or both?`
4. Point out that the widget now shows:
   - router selection
   - tool usage
   - final grounded response
5. Open Kagent UI and mention that the same prototype is also running as a managed Kagent agent in GKE.

## What To Say

Use this framing:

`This prototype is aligned with Architecture B. The managed agent path, MCP tool layer, and Milvus-backed retrieval are live in GKE. For the prototype, I kept the LLM external through Groq and deferred heavier in-cluster pieces like KServe model serving and full Istio overhead so the demo stays fast, stable, and within practical resource limits.`

## Honest Caveat

The current MCP pod in the cluster is still using the working runtime fallback:

- existing API image
- mounted `server.py`
- `fastmcp` installed at startup

That is demo-safe and already accepted by Kagent, but the clean dedicated MCP image is still the next packaging step.
