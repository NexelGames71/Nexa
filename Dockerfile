FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY nexa ./nexa

RUN pip install --no-cache-dir .

EXPOSE 8000

# Portable ASGI service: runs on Docker, Cloud Run, Fly.io, ECS, K8s,
# or any host. No platform-specific APIs are used.
CMD ["sh", "-c", "uvicorn nexa.main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS:-1}"]
