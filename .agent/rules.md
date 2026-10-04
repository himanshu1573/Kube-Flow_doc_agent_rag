# Rules for agents changing this repository

## Security and secrets

- Never commit `.env`, API keys, kubeconfigs or tokens. Before committing, check
  `git diff --cached` for `gsk_`, `sk-`, `AIza`, `hf_`, `ghp_` and private key blocks.
- New configuration goes into `.env.example` with a safe placeholder, and into the README
  configuration table.
- **Client keys** (`X-LLM-API-Key`) are per-request credentials:
  - never `print`/log them, put them in thread state, or include them in responses or errors
  - send them only to `KSERVE_URL`; never let a client choose the LLM URL (SSRF)
  - the widget stores them in `sessionStorage` only, never `localStorage` or cookies
- Do not hard-code project IDs, public IPs or personal paths. Use placeholders such as
  `<PROJECT_ID>`, `<API_DOMAIN>` and `<REGISTRY>`.
- The widget renders model output only through `renderMarkdown()` (marked + DOMPurify, with an
  escaped-text fallback). Never assign model or server strings to `innerHTML` directly; use
  `textContent`. Chat history is persisted as data (`kf-chat-v2`), never as HTML.

## Invariants (breaking these breaks retrieval or the API contract)

- `EMBEDDING_MODEL` is the same for ingestion and serving. After changing it, re-ingest with
  `scripts/ingest_local.py all --recreate`. Dimensions live in
  `pipelines/shared/embedding_utils.get_embedding_dimension`.
- Collection schemas live in `backend/schemas/`. Changing fields requires recreating the
  collections and updating `agent/core/retriever.py` output fields.
- `chunk_id` must stay deterministic. Loaders upsert by it, so re-runs must not duplicate data.
- One user turn makes at most **two** LLM calls: tool selection, then a single answer call that
  gets all results as plain context, with no tools and the answer-only system prompt
  (`server-https/app.py`, `build_answer_system_prompt`). Do not reintroduce a follow-up per tool,
  tool definitions in the answer step, or the `tool_use_failed` fallback on the answer step
  (it loops).
- SSE event types (`thread`, `tool_result`, `content`, `citations`, `error`, `done`) are a contract
  with both widgets. Add fields if needed, but do not rename events.
- Error status mapping for non-streaming `/chat`: 400 malformed headers, 401 key missing or
  rejected, 429 rate limited, 502 other upstream failures.

## Code style

- Python 3.12 locally (Docker images use 3.11). Follow the surrounding style: type hints, small
  functions, `print(f"[TAG] ...")` logging in the servers, `logging` in pipelines.
- Shared logic goes in `agent/core/` or `pipelines/shared/`, not copied into each server.
- Keep diffs minimal: no drive-by reformatting, no renames without a reason.
- Do not hand-edit generated KFP YAML (`pipelines/**/pipeline.yaml`). Regenerate with
  `make compile-pipelines`, and only commit it when the pipeline changed.
- Widget JS is dependency-free vanilla JS. Check it with `node --check <file>`.

## Tests

- `make test` must pass before every commit. Tests must not need Milvus, network or real keys.
- Mock the LLM with `httpx.MockTransport` (see `FakeLLM` in `tests/test_server_app.py`). Mock
  retrieval by patching `execute_tool_call`.
- For every bug fix, first write a test that fails on the old code, then fix it.

## Commits

- Conventional commits: `feat(scope):`, `fix(scope):`, `docs:`, `test:`, `build:`, `chore:`.
- The body explains **why** (root cause and symptoms), not only what changed.
- One logical change per commit. Run `git status` and `git diff --cached` before committing.
- Do not push, force-push or open PRs unless the maintainer asks.

## Environment notes

- CPU-only works for everything except in-cluster KServe LLM serving.
- `uv` is the package manager (`make setup`). Do not install into the system Python.
- Free LLM tiers rate-limit hard (Groq: about 8k tokens per minute). Space out manual end-to-end
  queries by about 30–60 seconds.
