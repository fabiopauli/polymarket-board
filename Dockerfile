# ── Stage 1: build the Polymarket CLI (Rust) ─────────────────────────────────
FROM rust:latest AS rust-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    git pkg-config libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
# Clone directly from GitHub so the image builds correctly without submodule
# state (Railway and other CI systems may not fetch submodules by default).
RUN git clone --depth 1 https://github.com/Polymarket/polymarket-cli .
RUN cargo build --release

# ── Stage 2: Python runtime ───────────────────────────────────────────────────
FROM python:3.11-slim

# Install uv (fast Python package manager)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install Python dependencies first (layer-cached, only re-runs when deps change)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy application source
COPY dashboard.py server.py ./
COPY static/ static/

# Copy the compiled CLI binary from the build stage
COPY --from=rust-builder /build/target/release/polymarket /usr/local/bin/polymarket

# Point server.py at the binary; Railway injects PORT at runtime
ENV PM_BIN=/usr/local/bin/polymarket

EXPOSE 8000

# Use $PORT if set (Railway), fall back to 8000 for local docker run
CMD ["sh", "-c", ".venv/bin/uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000}"]
