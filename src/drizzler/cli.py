#!/usr/bin/env python3

import argparse
import asyncio
import logging
import os

from drizzler.core import RequestDrizzler
from drizzler.logging_config import setup_logging


def parse_args():
    parser = argparse.ArgumentParser(
        description="🌧️ Drizzler: Adaptive HTTP/Video Downloader with Host-Aware Throttling",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "urls",
        nargs="+",
        help="YouTube URLs or HTTP endpoints to fetch/download",
    )

    # yt-dlp Download Options
    parser.add_argument(
        "--write-video",
        action="store_true",
        help="Download actual video file (via yt-dlp)",
    )
    parser.add_argument(
        "--write-info-json",
        action="store_true",
        help="Write video metadata to .info.json file",
    )
    parser.add_argument(
        "--write-thumbnail",
        action="store_true",
        help="Download thumbnail image",
    )
    parser.add_argument(
        "--write-subs",
        action="store_true",
        help="Download subtitles/captions",
    )
    parser.add_argument(
        "--write-txt",
        action="store_true",
        help="Extract text only from captions (removes timestamps and metadata)",
    )
    parser.add_argument(
        "--summarize",
        action="store_true",
        help="Generate AI summary of caption text in markdown format",
    )
    parser.add_argument(
        "--mode",
        choices=["default", "lecture"],
        default="default",
        help="Summarization mode: 'default' for simple summaries, 'lecture' for structured blog-style summaries",
    )
    parser.add_argument(
        "--llm-provider",
        choices=["openai", "ollama", "transformers"],
        default="openai",
        help="LLM provider: 'openai' for OpenAI-compatible APIs (llama.cpp, vLLM), 'ollama', or 'transformers'",
    )
    parser.add_argument(
        "--llm-model",
        default="",
        help="Model to use for summarization (empty = use LLM_MODEL env var)",
    )
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Simulate only — fetch webpage or metadata, but do NOT download files",
    )

    # Output & Concurrency
    parser.add_argument(
        "-o",
        "--output-dir",
        default="./downloads",
        help="Output directory for downloads",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=5,
        help="Global concurrency (reduce for video downloads)",
    )
    parser.add_argument(
        "--rate",
        type=float,
        default=1.0,
        help="Per-host rate limit (requests per second)",
    )

    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable terminal progress bar",
    )
    parser.add_argument(
        "--proxy",
        type=str,
        help="Proxy URL (e.g., http://user:pass@host:port)",
    )

    # Logging & Debugging
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug-level logging",
    )
    parser.add_argument(
        "--log-file",
        type=str,
        default=None,
        help="Optional file to write logs to (e.g., drizzler.log)",
    )

    return parser.parse_args()


async def run():
    args = parse_args()

    # Setup logging
    log_level = "DEBUG" if args.debug else "INFO"
    setup_logging(level=log_level, log_file=args.log_file)

    # Validate: if --simulate, disable all writes
    if args.simulate:
        logging.info("--simulate enabled: disabling all file writes.")
        download_video = False
        download_info = False
        download_thumbnail = False
        download_subs = False
        download_txt = False
        summarize = False
    else:
        download_video = args.write_video
        download_info = args.write_info_json
        download_thumbnail = args.write_thumbnail
        download_subs = args.write_subs
        download_txt = args.write_txt
        summarize = args.summarize

    # If summarize is enabled, we need text extraction
    if summarize and not download_txt:
        download_txt = True
        logging.info("--summarize enabled: automatically enabling text extraction")

    # Ensure output dir exists
    os.makedirs(args.output_dir, exist_ok=True)

    # Initialize Drizzler
    drizzler = RequestDrizzler(
        urls=args.urls,
        per_host_rate=args.rate,
        global_concurrency=args.concurrency,
        request_timeout_s=60.0
        if (
            download_video
            or download_info
            or download_thumbnail
            or download_subs
            or download_txt
            or summarize
        )
        else 30.0,
        max_retries=3,
        slow_start_ramp_up_s=15.0,
        state_file="drizzler_state.json",
        deduplicate=True,
        download_video=download_video,
        download_info=download_info,
        download_thumbnail=download_thumbnail,
        download_subs=download_subs,
        download_txt=download_txt,
        summarize=summarize,
        summarize_mode=args.mode,
        llm_provider=args.llm_provider,
        llm_model=args.llm_model,
        output_dir=args.output_dir,
        simulate=args.simulate,
        use_progress_bar=not args.no_progress,
        proxy=args.proxy,
    )

    logging.info(
        f"Starting Drizzler with {len(args.urls)} URLs | "
        f"Mode: {'DOWNLOAD' if not args.simulate else 'SIMULATE'} | "
        f"Concurrency: {args.concurrency} | Rate: {args.rate} RPS"
    )

    # Run
    stats = await drizzler.run()

    # Final summary
    if stats is not None:
        mean_val = stats.mean if stats.mean is not None else 0.0
        logging.info(
            f"Run completed: {stats.success} succeeded, {stats.errors} failed | "
            f"Error rate: {stats.error_rate * 100:.1f}% | "
            f"Mean latency: {mean_val:.2f}s"
        )


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
