# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Drizzler is an adaptive, host-aware HTTP fetcher and YouTube downloader with intelligent throttling, state persistence, and AI summarization. It operates in two modes: CLI for single-shot execution and Web SaaS (FastAPI + React) for job-based processing.

## Development Commands

```bash
# Setup
just install              # Install Python + Node dependencies
just install-hooks        # Install pre-commit hooks

# Code Quality
just lint                 # Ruff check + format check
just fix                  # Auto-fix linting issues
just type                 # MyPy type checking
just check                # Run lint + type together
just pre-commit           # Run all pre-commit hooks

# Running the Application
just run <URL> [options]  # CLI mode
just api                  # FastAPI backend (port 8000)
just ui                   # React dev server (Vite)
just web                  # Run both API and UI in parallel
just deploy-local         # Build UI + run unified server

# Docker
just docker-build         # Build image
just docker-run <URL>     # Run container
```

## Architecture

```
src/drizzler/
├── cli.py           # CLI entry point, argument parsing
├── core.py          # RequestDrizzler engine - central orchestrator (~800 LOC)
├── throttling.py    # BoundedTokenBucket (rate limiting) + HostCircuitBreaker
├── api/
│   ├── main.py      # FastAPI app with endpoints
│   └── jobs.py      # JobManager for async job tracking
├── summarizer.py    # TextSummarizer (Gemini, Ollama, OpenAI-compatible)
├── metrics.py       # Stats computation (mean, p50, p95, p99)
├── persistence.py   # StateManager for resume support
├── rendering.py     # Terminal visualization (histograms, timelines)
├── models.py        # Dataclasses (Stats, MetricsCallback, TimelineType)
└── utils.py         # Helpers (normalize_host, GracefulKiller)

ui/src/
├── App.jsx          # Main React component with job management UI
└── main.jsx         # Entry point
```

### Core Components

**RequestDrizzler** (`core.py`): The main engine that handles:
- URL deduplication and batching
- Concurrency control via global and per-host semaphores
- Per-host token bucket rate limiting with slow-start ramp-up
- Per-host circuit breakers for failure resilience
- YouTube downloads via yt-dlp delegation
- State persistence to `drizzler_state.json`

**Throttling** (`throttling.py`):
- `BoundedTokenBucket`: Token-bucket rate limiting with burst, slow-start (20% → 100%), and adaptive rate adjustment
- `HostCircuitBreaker`: Opens after consecutive failures, cooldown before retries

**API Backend** (`api/`):
- Job CRUD endpoints: `POST /api/jobs`, `GET /api/jobs`, `GET /api/jobs/{id}`, `DELETE /api/jobs/{id}`
- In-memory job storage with progress/stage callbacks for real-time UI updates

**Summarizer** (`summarizer.py`):
- Auto-detects provider from model name (gemini-* → Gemini API)
- Falls back to Ollama (`LLM_HOST/api/generate`) or OpenAI-compatible (`LLM_HOST/v1/chat/completions`)

## Key Design Patterns

1. **Async-First**: All I/O uses asyncio; `RequestDrizzler.run()` is the async main loop

2. **Host-Aware Throttling**: Each host gets its own token bucket and circuit breaker. YouTube CDN hosts are normalized (e.g., `*.googlevideo.com` → `youtube-cdn`)

3. **State Persistence**: Bucket rates and breaker states saved to JSON for resume support

4. **Dual-Mode**: Same core engine shared between CLI and Web modes

## Environment Variables

```bash
GOOGLE_API_KEY=<key>              # For Gemini summarization
LLM_MODEL=gemini-3-flash-preview  # Default LLM model
LLM_HOST=http://localhost:8003    # Local LLM server
YTDLP_COOKIES_PATH=cookies.txt    # Optional for restricted content
HTTP_REQUEST_TIMEOUT_S=10         # HTTP timeout
```

## Testing

```bash
just check       # Run lint + type checks
just pre-commit  # Run all pre-commit hooks
```

Test files are in `tests/` directory. Run with pytest.
