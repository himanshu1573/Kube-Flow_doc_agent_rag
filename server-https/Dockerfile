FROM python:3.11-slim

# Create non-root user
RUN useradd -m -u 1000 appuser
WORKDIR /app

# Install deps
COPY server-https/requirements.txt ./
RUN pip install --no-cache-dir --default-timeout=1000 -r requirements.txt

# Environment variables
ENV PORT=8000

# Switch to non-root before running the app
USER appuser

# App and shared runtime packages
COPY server-https/app.py /app/
COPY agent /app/agent
COPY pipelines /app/pipelines
COPY backend /app/backend

EXPOSE 8000
CMD ["python", "-u", "app.py"]
