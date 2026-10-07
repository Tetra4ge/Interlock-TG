# API image: the Python backend (hl CLI + FastAPI). The dashboard has its own image.
# Pinned to amd64: libsql==0.1.11 publishes no linux/arm64 wheel, and building it from
# source needs a Rust and C toolchain this image does not carry. On Apple Silicon, Docker
# Desktop runs this through emulation.
FROM --platform=linux/amd64 python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN pip install --no-cache-dir uv

# Dependencies first, so source edits do not invalidate this layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY server ./server
COPY config ./config
COPY scripts ./scripts
COPY data/chunks ./data/chunks
COPY data/vectors ./data/vectors
COPY data/samples ./data/samples
COPY data/eval ./data/eval
RUN uv sync --frozen --no-dev

# The run store lives in a volume so it survives container rebuilds.
RUN useradd -m app && mkdir -p /app/db && chown -R app /app
USER app

EXPOSE 8000
ENTRYPOINT ["bash", "scripts/entrypoint.sh"]
CMD ["api"]
