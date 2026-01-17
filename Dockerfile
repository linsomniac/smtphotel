# AIDEV-NOTE: Multi-stage Dockerfile for smtphotel
# Stage 1: Build with uv
# Stage 2: Runtime with minimal footprint

# Build stage
FROM python:3.13-slim AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /bin/uv

# Set up working directory
WORKDIR /app

# Copy dependency files first for better caching
COPY pyproject.toml uv.lock README.md ./

# Install dependencies using uv
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Copy source code
COPY src ./src

# Build wheel and install it (non-editable)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv build --wheel && \
    uv pip install --no-deps dist/*.whl


# Runtime stage
FROM python:3.13-slim

# Create non-root user for security
RUN groupadd -r smtphotel && useradd -r -g smtphotel smtphotel

# Set up working directory
WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy static files
COPY --from=builder /app/src/smtphotel/web/static /app/.venv/lib/python3.13/site-packages/smtphotel/web/static

# Create data directory
RUN mkdir -p /data && chown smtphotel:smtphotel /data

# Set environment variables
ENV PATH="/app/.venv/bin:$PATH"
ENV DB_PATH=/data/smtphotel.db
ENV BIND_ADDRESS=0.0.0.0

# Expose ports
EXPOSE 2525 8025

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8025/api/health')" || exit 1

# Switch to non-root user
USER smtphotel

# Run the application
CMD ["python", "-m", "smtphotel.main"]
