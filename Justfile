# Load environment variables from .env file
set dotenv-load := true

# Default recipe to display help
default:
    @just --list

# Variables
project_name := "drizzler"
python_version := "3.11"
docker_image := "drizzler:latest"
docker_registry := "ghcr.io/ziwon"  # GitHub Container Registry
version := `grep 'version = ' pyproject.toml | cut -d'"' -f2`

# ============================================================================
# Development Setup
# ============================================================================

# Install all dependencies including dev dependencies
install:
    uv sync --all-extras

# Install pre-commit hooks
install-hooks:
    uv run pre-commit install

# Update dependencies
update:
    uv lock --upgrade
    uv sync --all-extras

# Clean up generated files and caches
clean:
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
    find . -type f -name "*.pyc" -delete
    find . -type f -name "*.pyo" -delete
    find . -type f -name ".coverage" -delete
    rm -rf build/ dist/ *.egg-info 2>/dev/null || true
    rm -rf downloads/* 2>/dev/null || true

# ============================================================================
# Code Quality & Testing
# ============================================================================

# Run all linting and formatting
lint:
    uv run ruff check src/ tests/
    uv run ruff format --check src/ tests/

# Fix linting issues and format code
fix:
    uv run ruff check --fix src/ tests/
    uv run ruff format src/ tests/

# Run type checking
type:
    uv run mypy src/

# Run all checks (lint, type, test)
check: lint type

# Run pre-commit on all files
pre-commit:
    uv run pre-commit run --all-files

# Run pre-commit on specific files
pre-commit-file *FILES:
    uv run pre-commit run --files {{FILES}}

# ============================================================================
# Application Commands
# ============================================================================

# Run the CLI with default arguments
run *ARGS:
    uv run python -m drizzler.cli {{ARGS}}

# Download videos from a URL file (reads URLs and passes them as arguments)
download-from-file file="urls.txt" *ARGS:
    @cat {{file}} | xargs uv run python -m drizzler.cli {{ARGS}}

# Run with video download enabled
download-video url *ARGS:
    uv run python -m drizzler.cli --write-video {{url}} {{ARGS}}

# Run with info JSON download
download-info url *ARGS:
    uv run python -m drizzler.cli --write-info {{url}} {{ARGS}}

# Run with custom output directory
download-to dir url *ARGS:
    uv run python -m drizzler.cli --output-dir {{dir}} {{url}} {{ARGS}}

# Monitor downloads with watch
watch:
    watch -n 1 "ls -la downloads/ | tail -20"

# ============================================================================
# Docker Commands
# ============================================================================

# Build Docker image
docker-build:
    docker build -t {{docker_image}} .
    docker tag {{docker_image}} {{docker_registry}}/{{docker_image}}

# Build Docker image with no cache
docker-rebuild:
    docker build --no-cache -t {{docker_image}} .
    docker tag {{docker_image}} {{docker_registry}}/{{docker_image}}

# Run Docker container interactively (ex.just docker-run url1, url2, ...)
docker-run *ARGS:
    docker run -it --rm \
        -v $(pwd)/downloads:/downloads \
        -v $(pwd)/.env:/app/.env:ro \
        {{docker_image}} {{ARGS}}

# Run Docker with URLs from file (non-interactive)
docker-run-file file="urls.txt" *ARGS:
    @cat {{file}} | grep -E '^https?://' | cut -d' ' -f1 | xargs docker run --rm \
        -v $(pwd)/downloads:/downloads \
        -v $(pwd)/.env:/app/.env:ro \
        {{docker_image}} {{ARGS}}

# Run Docker container in background
docker-run-daemon name="drizzler" *ARGS:
    docker run -d \
        --name {{name}} \
        -v $(pwd)/downloads:/downloads \
        -v $(pwd)/.env:/app/.env:ro \
        --restart unless-stopped \
        {{docker_image}} {{ARGS}}

# Stop and remove Docker container
docker-stop name="drizzler":
    docker stop {{name}} || true
    docker rm {{name}} || true

# View Docker container logs
docker-logs name="drizzler":
    docker logs -f {{name}}

# Execute command in running container
docker-exec name="drizzler" *CMD:
    docker exec -it {{name}} {{CMD}}

# Check if CR_PAT is configured
docker-check-auth:
    @if [ -z "$CR_PAT" ]; then \
        echo "❌ CR_PAT environment variable is not set"; \
        echo "   Set it with: export CR_PAT=<your-github-personal-access-token>"; \
        echo "   Create a token at: https://github.com/settings/tokens"; \
        echo "   Required scopes: write:packages, read:packages, delete:packages"; \
        exit 1; \
    else \
        echo "✅ CR_PAT is configured"; \
    fi

# Login to GitHub Container Registry (requires CR_PAT environment variable)
docker-login: docker-check-auth
    @echo "Logging into GitHub Container Registry..."
    @echo "$CR_PAT" | docker login ghcr.io -u ziwon --password-stdin

# Push Docker image to registry (auto-login if CR_PAT is set)
docker-push: docker-build
    @if [ -n "$CR_PAT" ]; then \
        echo "$CR_PAT" | docker login ghcr.io -u ziwon --password-stdin; \
    fi
    docker push {{docker_registry}}/{{docker_image}}
    @echo "Pushed image to {{docker_registry}}/{{docker_image}}"

# Pull Docker image from registry
docker-pull:
    docker pull {{docker_registry}}/{{docker_image}}
    docker tag {{docker_registry}}/{{docker_image}} {{docker_image}}

# Clean up Docker resources
docker-clean:
    docker system prune -f
    docker image prune -f

# Show Docker image info
docker-info:
    @echo "Local image: {{docker_image}}"
    @docker images {{docker_image}}
    @echo ""
    @echo "Registry image: {{docker_registry}}/{{docker_image}}"
    @docker images {{docker_registry}}/{{docker_image}}

# Build and push in one command
docker-release: docker-build docker-push
    @echo "Successfully built and pushed {{docker_registry}}/{{docker_image}}"

# Build and tag with version
docker-build-version:
    docker build -t {{project_name}}:{{version}} .
    docker tag {{project_name}}:{{version}} {{docker_registry}}/{{project_name}}:{{version}}
    docker tag {{project_name}}:{{version}} {{docker_registry}}/{{project_name}}:latest
    @echo "Built and tagged version {{version}}"

# Push versioned image to registry
docker-push-version: docker-build-version
    @if [ -n "$CR_PAT" ]; then \
        echo "$CR_PAT" | docker login ghcr.io -u ziwon --password-stdin; \
    fi
    docker push {{docker_registry}}/{{project_name}}:{{version}}
    docker push {{docker_registry}}/{{project_name}}:latest
    @echo "Pushed version {{version}} and latest tags"

# Run container from registry image
docker-run-remote *ARGS:
    docker run -it --rm \
        -v $(pwd)/downloads:/downloads \
        -v $(pwd)/.env:/app/.env:ro \
        {{docker_registry}}/{{docker_image}} {{ARGS}}

# ============================================================================
# Development Tools
# ============================================================================

# Start development server with auto-reload
dev *ARGS:
    uv run python -m drizzler.cli --debug {{ARGS}}

# Open Python REPL with project imports
repl:
    uv run python -c "from drizzler import *; import asyncio; import aiohttp"

# Generate requirements.txt from uv.lock
requirements:
    uv export --no-hashes > requirements.txt
    uv export --no-hashes --extra dev > requirements-dev.txt

# Check for outdated dependencies
outdated:
    uv pip list --outdated

# ============================================================================
# Documentation & Release
# ============================================================================

# Generate changelog from git commits
changelog:
    git log --pretty=format:"- %s" $(git describe --tags --abbrev=0)..HEAD

# Create a new git tag
tag version:
    git tag -a v{{version}} -m "Release version {{version}}"
    @echo "Created tag v{{version}}"
    @echo "Run 'git push origin v{{version}}' to push the tag"

# Build Python package
build:
    uv build

# ============================================================================
# Utility Commands
# ============================================================================

# Show project statistics
stats:
    @echo "=== Project Statistics ==="
    @echo "Lines of Python code:"
    @find src -name "*.py" -type f | xargs wc -l | tail -1
    @echo ""
    @echo "Number of Python files:"
    @find src -name "*.py" -type f | wc -l
    @echo ""
    @echo "Number of tests:"
    @find tests -name "test_*.py" -type f -exec grep -c "def test_" {} \; | awk '{sum+=$1} END {print sum}'

# Find TODO comments in code
todos:
    @grep -r "TODO\|FIXME\|XXX" src/ tests/ --include="*.py" || echo "No TODOs found!"

# Create .env file from example
env:
    cp .env.example .env
    @echo "Created .env file from .env.example"
    @echo "Please edit .env with your configuration"

# Show current environment info
info:
    @echo "Project: {{project_name}}"
    @echo "Python: {{python_version}}"
    @echo "Docker Image: {{docker_image}}"
    @echo "Working Directory: $(pwd)"
    @echo "Downloads Directory: $(pwd)/downloads"
    @uv --version
    @python --version

# Backup download directory
backup:
    tar -czf downloads-backup-$(date +%Y%m%d-%H%M%S).tar.gz downloads/
    @echo "Backup created: downloads-backup-$(date +%Y%m%d-%H%M%S).tar.gz"


# ============================================================================
# Help & Documentation
# ============================================================================

# Show help for a specific recipe
help recipe:
    @just --show {{recipe}}

# List all available recipes with descriptions
list:
    @just --list --unsorted
