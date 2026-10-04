ARG BASE_IMAGE
FROM ${BASE_IMAGE}

USER root
RUN pip install --no-cache-dir fastmcp

COPY kagent-feast-mcp/mcp-server/server.py /app/server.py

ENV PORT=8000 \
    PYTHONUNBUFFERED=1

USER appuser

CMD ["python", "-u", "/app/server.py"]
