# ── Stage 1: Build React Frontend ──────────────────────────────────────────────
FROM node:24-alpine AS frontend-builder

WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# ── Stage 2: Python Backend Runtime ───────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock

# Copy application code
COPY backend/ ./backend/
COPY config/ ./config/
COPY energyplus/ ./energyplus/
COPY run.py .

# Copy compiled frontend from Stage 1
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Run without root privileges; named volumes retain writable application data.
RUN groupadd --gid 10001 ecoloop && useradd --uid 10001 --gid ecoloop --no-create-home ecoloop \
    && mkdir -p logs data output energyplus/run \
    && chown -R ecoloop:ecoloop logs data output energyplus/run
USER ecoloop
ENV ENVIRONMENT=production REQUIRE_API_KEY=true PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# Run the application
CMD ["python", "-m", "uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
