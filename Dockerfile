# ── Base image ──────────────────────────────────────────────────────────────
# Use NVIDIA CUDA base for GPU support; falls back to CPU automatically.
# To build CPU-only: docker build --build-arg BASE=python:3.12-slim .
ARG BASE=nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04
FROM ${BASE}

# ── System dependencies ──────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.12 python3.12-venv python3.12-dev python3-pip \
    ffmpeg \
    libsndfile1 \
    tesseract-ocr \
    git \
    && rm -rf /var/lib/apt/lists/*

# Make python3.12 the default python3.
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1 \
    && update-alternatives --install /usr/bin/python  python  /usr/bin/python3.12 1

# ── Working directory ────────────────────────────────────────────────────────
WORKDIR /app

# ── Python dependencies (two-stage for layer caching) ────────────────────────
COPY requirements-app.txt .
RUN python3 -m pip install --upgrade pip \
    && python3 -m pip install --no-cache-dir -r requirements-app.txt

# ── Application source ───────────────────────────────────────────────────────
COPY . .

# ── Data directories (override with bind-mounts in production) ───────────────
RUN mkdir -p data/audio data/models

# ── Runtime configuration ─────────────────────────────────────────────────────
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOST=0.0.0.0 \
    PORT=8766

EXPOSE 8766

# ── Entrypoint ────────────────────────────────────────────────────────────────
CMD ["python3", "-m", "app.main"]
