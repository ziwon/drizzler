# Stage 1: Build UI
FROM node:20-slim AS ui-builder
WORKDIR /ui
COPY ui/package*.json ./
RUN npm install
COPY ui/ ./
RUN npm run build

# Stage 2: Python Backend
FROM python:3.11-slim

WORKDIR /app

# Install system deps for yt-dlp (including ffmpeg for video processing)
RUN apt-get update && apt-get install -y \
    git \
    ca-certificates \
    brotli \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install --no-cache-dir uv

# Copy project files
COPY pyproject.toml uv.lock README.md ./
COPY .env.example .env
COPY src/ ./src/

# Install python dependencies
RUN uv pip install --system --no-cache -e ".[web]"

# Copy built UI from stage 1
COPY --from=ui-builder /ui/dist ./ui/dist

# Create downloads dir
RUN mkdir -p /downloads/jobs

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Expose the API port
EXPOSE 8000

# Default command: run the API
ENTRYPOINT ["uvicorn", "drizzler.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
