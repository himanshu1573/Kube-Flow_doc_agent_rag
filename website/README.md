# Website integration: Kubeflow Docs Agent widget

These files add the chat assistant to the [kubeflow/website](https://github.com/kubeflow/website)
Hugo site. Every page then gets a floating "Kubeflow Agent" button. It streams answers from
the agent API (`server-https/app.py`) and sends the current page title and path as context.

```
website/
├── static/js/agent-widget.js          # widget (vanilla JS, SSE streaming, thread persistence)
├── static/css/agent-widget.css        # widget styles
├── layouts/partials/agent-widget.html # Hugo partial that loads the widget + API URL config
├── Dockerfile                         # builds the full Hugo site into an nginx image
└── deploy/
    ├── nginx/default.conf             # static file server on :8080
    └── gke/website.yaml.tmpl          # GKE Deployment/Service/Ingress/ManagedCertificate
```

## 1. Apply to a kubeflow/website checkout

```bash
git clone https://github.com/kubeflow/website.git kubeflow-website
cp -R website/static website/layouts website/deploy website/Dockerfile kubeflow-website/
```

Then add this line at the end of `kubeflow-website/layouts/partials/footer.html`:

```go-html-template
{{ partial "agent-widget.html" . }}
```

## 2. Run locally

Start the agent API on `http://localhost:8000` first. See the root [README](../README.md#quick-start-local-no-cloud).

```bash
cd kubeflow-website
npm ci
hugo server            # http://localhost:1313/docs/
```

On `localhost` / `127.0.0.1` the widget calls `http://localhost:8000/chat` by default.

## 3. Choose the API URL

The widget picks its backend in this order:

1. `params.agentApiUrl` in the Hugo config, or the env var `HUGO_PARAMS_AGENTAPIURL=https://agent.example.com/chat`.
   The partial renders this into `window.KUBEFLOW_AGENT_CONFIG.apiUrl`.
2. `http://localhost:8000/chat` when the page is served from localhost.
3. `/api/agent/chat` on the same origin. Use this when a reverse proxy (Netlify redirect, ingress)
   forwards that path to the agent API.

The API sends `Access-Control-Allow-Origin: *`. Restrict it to your site's origin before a real
production rollout.

## 4. Bring your own LLM API key

The key icon in the panel header opens **Use your own LLM API key**:

- **Save key** stores the key (and an optional model) in `sessionStorage`. It is cleared when the
  tab closes and never written to `localStorage`.
- Each question sends the key to the agent API as the `X-LLM-API-Key` header (and `X-LLM-Model`).
  The API uses it for that request only and does not log or store it.
- **Clear key** removes it immediately. The widget then falls back to the server's key, if the
  deployment has one.
- On startup the widget reads `GET /config`. It shows which provider the key is for (for example
  `api.groq.com`), and shows "API key required" when the server sets `REQUIRE_CLIENT_API_KEY=true`.
- If the provider rejects the key (401), the widget shows the error and reopens the key panel.

For a public deployment, set `REQUIRE_CLIENT_API_KEY=true` on the API so visitors never spend the
operator's key.

To preview locally without Hugo, run `make web` and open
`http://127.0.0.1:8090/website/preview.html`.

## 5. Build and deploy the website image (optional)

```bash
docker build -t <REGISTRY>/kubeflow-website:latest \
  --build-arg HUGO_BASEURL=https://<WEBSITE_DOMAIN>/ \
  --build-arg AGENT_API_URL=https://<API_DOMAIN>/chat .
docker push <REGISTRY>/kubeflow-website:latest

sed -e "s#__IMAGE__#<REGISTRY>/kubeflow-website:latest#" \
    -e "s#__DOMAIN__#<WEBSITE_DOMAIN>#" deploy/gke/website.yaml.tmpl | kubectl apply -f -
```

The GKE template expects a reserved global static IP named `kubeflow-website-global`.
