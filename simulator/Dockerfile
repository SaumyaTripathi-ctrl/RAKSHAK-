# Build context is the repository root:  docker build -f simulator/Dockerfile .
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY ml/pyproject.toml ml/pyproject.toml
COPY ml/rakshak_ml ml/rakshak_ml
COPY backend/pyproject.toml backend/pyproject.toml
COPY backend/rakshak backend/rakshak
COPY simulator/pyproject.toml simulator/pyproject.toml
COPY simulator/rakshak_sim simulator/rakshak_sim
# The simulator needs only the codec (cryptography) and the physics (numpy): skip pandas/scikit-learn.
RUN pip install --no-deps ./ml && pip install ./backend ./simulator

EXPOSE 8100
HEALTHCHECK --interval=10s --timeout=3s --retries=10 --start-period=10s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8100/health',timeout=2).status==200 else 1)"
CMD ["python", "-m", "rakshak_sim"]
