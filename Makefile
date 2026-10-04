# Local developer workflow. Run `make help` for targets.
# Requires: uv, Docker. Settings come from .env (copy .env.example).

PY        := .venv/bin/python
LOAD_ENV  := set -a; [ -f .env ] && . ./.env; set +a; export PYTHONPATH=$(CURDIR);
MAX_PAGES ?= 20

.PHONY: help setup milvus-up milvus-down ingest-docs ingest-code ingest api web test compile-pipelines

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

setup: ## Create .venv (Python 3.12) and install local dependencies
	uv venv --python 3.12 .venv
	uv pip install --python $(PY) -r requirements-local.txt
	@[ -f .env ] || (cp .env.example .env && echo "Created .env from .env.example - set LLM_API_KEY")

milvus-up: ## Start Milvus standalone in Docker and wait until healthy
	docker compose up -d --wait milvus

milvus-down: ## Stop Milvus (data stays in ./volumes)
	docker compose down

ingest-docs: ## Crawl kubeflow.org/docs into docs_collection (MAX_PAGES=20)
	$(LOAD_ENV) $(PY) scripts/ingest_local.py docs --max-pages $(MAX_PAGES)

ingest-code: ## Parse kubeflow/manifests into code_collection (~4 min on CPU)
	$(LOAD_ENV) $(PY) scripts/ingest_local.py code

ingest: ingest-docs ingest-code ## Run docs and code ingestion

api: ## Run the agent API on http://localhost:8000
	$(LOAD_ENV) $(PY) server-https/app.py

web: ## Serve widget previews: /website/preview.html and /demo/agent-section-demo.html on :8090
	@echo "Website widget: http://127.0.0.1:8090/website/preview.html"
	@echo "Demo page:      http://127.0.0.1:8090/demo/agent-section-demo.html"
	$(PY) -m http.server 8090 --bind 127.0.0.1

test: ## Run unit tests (no Milvus or LLM needed)
	PYTHONPATH=$(CURDIR) $(PY) -m unittest discover -s tests -v

compile-pipelines: ## Compile the Kubeflow Pipelines to YAML
	PYTHONPATH=$(CURDIR) $(PY) pipelines/docs_ingestion/pipeline.py
	PYTHONPATH=$(CURDIR) $(PY) pipelines/code_ingestion/pipeline.py
