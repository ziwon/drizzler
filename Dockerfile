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

COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/

RUN uv pip install --system --no-cache -e .

# Create downloads dir (In prod, it mounts to the NAS storage)
RUN mkdir -p /downloads

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Default command
ENTRYPOINT ["python", "-m", "drizzler.cli"]
