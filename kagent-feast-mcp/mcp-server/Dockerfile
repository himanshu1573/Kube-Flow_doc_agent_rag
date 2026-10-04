FROM python:3.10-slim

WORKDIR /app

COPY kagent-feast-mcp/mcp-server/requirements.txt .
RUN pip install -r requirements.txt

RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-base-en-v1.5')"

COPY kagent-feast-mcp/mcp-server/server.py .
COPY agent /app/agent
COPY pipelines /app/pipelines
COPY backend /app/backend

ENV PORT=8000

EXPOSE 8000

CMD ["python", "server.py"]
