# Antigravity Context: Kubeflow Website Agent Integration

## Goal

Integrate the Kubeflow Docs Agent into the Kubeflow Hugo website so it works:

- locally on `http://localhost:1313/docs/`
- on Netlify deploy previews
- on the production website at `https://www.kubeflow.org/docs/`

## Current Status

The website-side widget is already integrated into the docs layout and is visible on the local docs site.

Verified:

- local docs site responds at `http://localhost:1313/docs/`
- the docs HTML includes:
  - `/css/agent-widget.css?v=2`
  - `/js/agent-widget.js?v=2`
- the widget appears in the docs UI and opens as a right-side assistant panel

## Website Integration Points

The widget is injected globally from the website repo here:

- [footer.html](https://github.com/kubeflow/website/blob/master/layouts/partials/footer.html:57)
- [agent-widget.js](../../website/static/js/agent-widget.js:1)
- [agent-widget.css](../../website/static/css/agent-widget.css:1)

Important detail:

- the widget is not missing from Hugo
- the widget is already loaded by the website

So the remaining problem is not layout integration.

## Local Demo Setup

The local setup works because:

1. Hugo serves the website on `http://localhost:1313`
2. the backend API is port-forwarded to `http://localhost:8000/chat`
3. the widget calls that local backend

That is why the local screenshot works.

## Backend Status

The backend side is already running as an Architecture B-style prototype on GKE:

- Kagent controller is running
- managed agent is running
- MCP server is running
- Milvus is populated
- FastAPI chat endpoint works

For local website testing, the relevant endpoint is:

- `http://localhost:8000/chat`

## What Was Fixed

The website widget used to be hardcoded to:

- `http://localhost:8000/chat`

That is fine for local testing, but it breaks on deployed website builds.

I updated the widget so it now supports runtime configuration:

- [agent-widget.js](../../website/static/js/agent-widget.js:8)

Current behavior:

- on `localhost`, it defaults to `http://localhost:8000/chat`
- on non-localhost environments, it defaults to `/api/agent/chat`
- it can also be overridden by:
  - `window.KUBEFLOW_AGENT_CONFIG.apiUrl`
  - `localStorage["kubeflow_agent_api_url"]`

This means the widget code is now deployment-ready from the frontend side.

## Final Blocker

The final blocker is:

**there is no public HTTPS backend route yet for the website to call in production**

More specifically:

- the website is static and deployed via Netlify
- the backend currently works through localhost port-forwarding or internal cluster networking
- production website users cannot call `localhost:8000`
- the default production path `/api/agent/chat` does not exist yet on the deployed site

So the actual blocker is not Hugo and not CSS/JS injection.

The blocker is:

**public routing from the website to the agent backend**

## What Must Be Done Next

Choose one of these production paths:

### Option 1: Public Backend URL

Expose the FastAPI chat backend on a public HTTPS URL, for example:

- `https://agent-api.your-domain.com/chat`

Then set:

```html
<script>
  window.KUBEFLOW_AGENT_CONFIG = {
    apiUrl: "https://agent-api.your-domain.com/chat"
  };
</script>
```

This is the simplest path.

### Option 2: Same-Domain Proxy

Keep the widget calling:

- `/api/agent/chat`

Then create a reverse proxy from the website deployment to the backend.

Because the Kubeflow website is deployed on Netlify, this likely means:

- Netlify redirect/proxy rule, or
- another same-domain edge/proxy layer in front of the backend

This is the cleanest UX because the frontend stays same-origin.

## Recommended Path

For the prototype, the fastest path is:

1. expose FastAPI publicly on HTTPS
2. set `window.KUBEFLOW_AGENT_CONFIG.apiUrl`
3. verify CORS for `https://www.kubeflow.org`
4. deploy the website PR and test in Netlify preview

## Deployment Notes For Kubeflow Website

The website repo is Hugo + Docsy and deploys through Netlify.

Relevant files:

- [README.md](https://github.com/kubeflow/website/blob/master/README.md:1)
- [netlify.toml](https://github.com/kubeflow/website/blob/master/netlify.toml:1)

Production deploy path:

1. commit the website changes
2. push a branch
3. open a PR against `kubeflow/website`
4. let Netlify create a deploy preview
5. test the widget in the preview
6. merge to trigger production deploy

## Important Caveat

There is still a separate backend packaging cleanup item:

- the MCP pod currently uses a working runtime fallback instead of the final dedicated image

That is real, but it is **not** the website integration blocker.

The website blocker is still the missing public HTTPS route to the chat API.

## Short Summary

What is done:

- widget is already integrated into Hugo docs pages
- local docs page shows the assistant
- backend works locally through port-forward
- widget config is now runtime-friendly

What is blocked:

- deployed website has no public backend route yet

What needs to happen:

- expose backend publicly or proxy `/api/agent/chat`
- then test on Netlify preview
- then merge website PR
