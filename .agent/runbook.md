# Runbook: run and verify the stack locally

Follow these steps in order. Each step lists the command, what success looks like, and what to do
if it fails. All commands run from the repo root.

## 0. Prerequisites

```bash
docker info >/dev/null && echo docker-ok      # Docker daemon running
uv --version                                   # uv installed
```

You also need an OpenAI-compatible LLM key with tool calling. Groq works:
`KSERVE_URL=https://api.groq.com/openai/v1/chat/completions`. Ports 8000, 8090, 9091 and 19530
must be free (`lsof -iTCP:8000 -sTCP:LISTEN`).

## 1. Install

```bash
make setup
```

**Success:** `.venv/` exists and `.env` is created from `.env.example`. Set `LLM_API_KEY` in `.env`,
or plan to send `X-LLM-API-Key` per request.

## 2. Unit tests (no services needed)

```bash
make test
```

**Success:** `Ran 25 tests ... OK` (the count grows as tests are added). Stop and fix anything else
before going on.

## 3. Vector database

```bash
make milvus-up
curl -s localhost:9091/healthz        # → OK
```

**If it fails:** run `docker compose logs milvus`. On low-memory machines, give Docker at least 4 GB.

## 4. Ingest

```bash
make ingest-docs                      # MAX_PAGES=20 by default; about 2 min
make ingest-code                      # kubeflow/manifests; about 4 min on CPU
```

**Success:** log lines like
`docs: load summary {'inserted': 379, 'failed': 0, ...}` and
`code: load summary {'inserted': 6378, 'failed': 0, ...}`. Counts vary with upstream content.
`failed` must be 0.

**If it fails:** a dimension mismatch means `EMBEDDING_MODEL` changed. Rerun with
`.venv/bin/python scripts/ingest_local.py all --recreate`, using the same env as `make`.

## 5. API

```bash
make api                              # foreground; use a second terminal for the rest
curl -s localhost:8000/health         # {"status":"healthy",...}
curl -s localhost:8000/config         # provider host, model, key policy
```

## 6. End-to-end questions

Space these about 60 seconds apart on free LLM tiers.

```bash
curl -s localhost:8000/chat -H 'Content-Type: application/json' \
  -d '{"message":"What is Kubeflow Pipelines?","stream":false}'
# expect: "route":"docs", citations under https://www.kubeflow.org/docs/...

curl -s localhost:8000/chat -H 'Content-Type: application/json' \
  -d '{"message":"How do I configure the notebook mutating webhook YAML?","stream":false}'
# expect: "route":"code", citations like https://github.com/kubeflow/manifests/blob/master/...#L1
```

Check bring-your-own-key handling:

```bash
curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/chat -H 'Content-Type: application/json' \
  -H 'X-LLM-API-Key: invalid-test-key-123' -d '{"message":"hi","stream":false}'
# expect: 401 (provider rejected the key), and the key must not appear in the API log
```

| Response | Meaning |
|---|---|
| 429 | Provider token limit. Wait and retry. The API log line `[ERROR] LLM HTTP 429: ...` has the exact quota. |
| 404 in the log | The model was retired. Set `MODEL` to a currently served model. |
| 502 | Other upstream failure. Read the `[ERROR] LLM HTTP` line. |

## 7. Widget

```bash
make web
```

Open `http://127.0.0.1:8090/website/preview.html` and click the blue button.
- Ask a question. The answer streams with sources.
- Click the key icon, then **Save key**. The header shows "Using your API key".
  **Clear key** returns it to "Online".

## 8. Clean up

```bash
# Ctrl+C the api and web processes
make milvus-down                      # data stays in ./volumes; rm -rf volumes to reset
```

## Deploying instead of running locally

See [docs/deploy-gke.md](../docs/deploy-gke.md) (GKE), [deploy/live/README.md](../deploy/live/README.md)
(Kagent + MCP) and [website/README.md](../website/README.md) (website widget). For public
deployments, set `REQUIRE_CLIENT_API_KEY=true`.
