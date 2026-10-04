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

## 4. Build and deploy the website image (optional)

```bash
docker build -t <REGISTRY>/kubeflow-website:latest \
  --build-arg HUGO_BASEURL=https://<WEBSITE_DOMAIN>/ \
  --build-arg AGENT_API_URL=https://<API_DOMAIN>/chat .
docker push <REGISTRY>/kubeflow-website:latest

sed -e "s#__IMAGE__#<REGISTRY>/kubeflow-website:latest#" \
    -e "s#__DOMAIN__#<WEBSITE_DOMAIN>#" deploy/gke/website.yaml.tmpl | kubectl apply -f -
```

The GKE template expects a reserved global static IP named `kubeflow-website-global`.
