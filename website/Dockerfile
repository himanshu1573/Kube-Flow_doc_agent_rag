FROM node:18-bookworm-slim AS builder

ARG HUGO_VERSION=0.124.1

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl git ca-certificates tar && \
    rm -rf /var/lib/apt/lists/* && \
    curl -L "https://github.com/gohugoio/hugo/releases/download/v${HUGO_VERSION}/hugo_extended_${HUGO_VERSION}_linux-amd64.tar.gz" -o /tmp/hugo.tar.gz && \
    tar -xzf /tmp/hugo.tar.gz -C /tmp && \
    mv /tmp/hugo /usr/local/bin/hugo && \
    chmod +x /usr/local/bin/hugo

WORKDIR /src

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

ARG HUGO_BASEURL=https://example.com/
# Public URL of the agent /chat endpoint, read by layouts/partials/agent-widget.html.
ARG AGENT_API_URL=""
ENV HUGO_ENV=production
ENV HUGO_PARAMS_AGENTAPIURL=${AGENT_API_URL}

# Build the full site so every page gets the chatbot widget and the correct base URL.
RUN hugo --gc --minify --baseURL "${HUGO_BASEURL}"

FROM nginx:1.27-alpine

COPY deploy/nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /src/public /usr/share/nginx/html
