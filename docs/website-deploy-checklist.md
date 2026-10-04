# Website Deploy Checklist

Use this checklist before deploying the Kubeflow website with the AI widget enabled.

## Public Backend Target

- HTTPS host: `https://<API_DOMAIN>`
- Chat endpoint: `https://<API_DOMAIN>/chat`
- Health endpoint: `https://<API_DOMAIN>/health`

## Deploy Website Only When These Are True

1. The GKE ingress has an external address.
2. The managed certificate for `<API_DOMAIN>` is `Active`.
3. `curl https://<API_DOMAIN>/health` returns HTTP `200`.
4. `curl -X POST https://<API_DOMAIN>/chat` returns a real response for a simple query.
5. The widget works from a non-local browser session without `kubectl port-forward`.

## Why Wait

If you deploy the website before the HTTPS endpoint is stable, the widget will load on the docs site but fail when users send messages. That would make the website look broken even though the backend logic is fine.

## Safe Deployment Order

1. Finish HTTPS ingress setup.
2. Confirm certificate is active.
3. Test `health` and one real `chat` request over public HTTPS.
4. Deploy the Kubeflow website.
5. Test 5 showcase questions on the deployed site.

## Suggested Showcase Questions

- `What is Kubeflow?`
- `How do I install Kubeflow?`
- `What is KServe?`
- `How do I configure the mutating webhook YAML for notebooks?`
- `How do I install Kubeflow using manifests?`
