# Build context is the repository root (it needs ml/ as well as backend/):
#   docker build -f backend/Dockerfile .
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

# 1) dependencies + packages
COPY ml/pyproject.toml ml/pyproject.toml
COPY ml/rakshak_ml ml/rakshak_ml
COPY backend/pyproject.toml backend/pyproject.toml
COPY backend/rakshak backend/rakshak
RUN pip install ./ml "./backend[api]"

# 2) train the spoilage models on SIMULATED shipments at build time (models are never committed)
RUN python -m rakshak_ml.train --out /app/artifacts --per-food 150 --stride 5
ENV RAKSHAK_MODEL_DIR=/app/artifacts/models

# 3) runtime files
COPY backend/alembic.ini backend/alembic.ini
COPY backend/alembic backend/alembic
COPY backend/docker-entrypoint.sh backend/docker-entrypoint.sh
WORKDIR /app/backend
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=10 --start-period=20s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health',timeout=2).status==200 else 1)"
ENTRYPOINT ["sh", "/app/backend/docker-entrypoint.sh"]
