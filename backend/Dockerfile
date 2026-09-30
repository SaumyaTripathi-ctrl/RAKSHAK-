FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml ./
COPY rakshak ./rakshak
RUN pip install ".[api,ml]"
COPY alembic.ini ./
COPY alembic ./alembic
COPY docker-entrypoint.sh ./
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=10 --start-period=15s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health',timeout=2).status==200 else 1)"
ENTRYPOINT ["sh", "/app/docker-entrypoint.sh"]
