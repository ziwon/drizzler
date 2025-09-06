"""
Minimal YouTube download test using yt-dlp as a library.

Usage:
  uv run examples/download_youtube.py "https://www.youtube.com/watch?v=m0Db3CAxzsE"
  uv run examples/download_youtube.py --write "https://www.youtube.com/watch?v=m0Db3CAxzsE"

If you need authenticated access, place a Netscape-format cookies.txt and set
YTDLP_COOKIES_PATH in your .env.
"""
import argparse
import os
from pathlib import Path

from dotenv import load_dotenv
from yt_dlp import YoutubeDL

load_dotenv()


def build_ydl_opts(write: bool, outdir: str = "downloads"):
    Path(outdir).mkdir(parents=True, exist_ok=True)
    cookies = os.getenv("YTDLP_COOKIES_PATH")
    common = {
        "outtmpl": str(Path(outdir) / "%(title).80s-%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": False,
        "nooverwrites": False,
        "ignoreerrors": True,
        "restrictfilenames": True,
        # Network robustness
        "retries": 3,
        "fragment_retries": 3,
        "skip_unavailable_fragments": True,
        "socket_timeout": 15,
        # Rate limit example (uncomment to cap download rate)
        # "ratelimit": 1_500_000,  # bytes/sec (~1.5MB/s)
    }
    if cookies:
        common["cookiefile"] = cookies

    if write:
        return common
    else:
        # simulate: do not write files; useful to test connectivity/metadata
        return {**common, "simulate": True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("url", help="YouTube video URL")
    parser.add_argument("--write", action="store_true", help="Actually write files (default: simulate only)")
    parser.add_argument("--outdir", default="downloads", help="Output directory")
    args = parser.parse_args()

    ydl_opts = build_ydl_opts(write=args.write, outdir=args.outdir)
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(args.url, download=args.write)
        # When simulate=True, this still fetches metadata and checks accessibility
        if info:
            print("Title:", info.get("title"))
            print("ID:", info.get("id"))
            print("Duration:", info.get("duration"))
            print("Uploader:", info.get("uploader"))
            print("Formats (sample):", [f.get("format_id") for f in info.get("formats", [])[:5]])
        else:
            print("Failed to fetch info for:", args.url)


if __name__ == "__main__":
    main()