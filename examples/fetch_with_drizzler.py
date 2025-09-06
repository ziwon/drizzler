# test_youtube.py
from drizzler import RequestDrizzler
from drizzler.logging_config import setup_logging
import asyncio

setup_logging(level="INFO")

URLS = [
    "https://www.youtube.com/watch?v=m0Db3CAxzsE",
    "https://www.youtube.com/watch?v=fAgAE9JmnOs",
    "https://www.youtube.com/watch?v=WKY-KFCvm-A",
    "https://www.youtube.com/watch?v=DzSb5b8ehdg",
    "https://www.youtube.com/watch?v=L1haw5kPB7Q",
    "https://www.youtube.com/watch?v=YVplo9mgtcs",
    "https://www.youtube.com/watch?v=VhBXWT6Oqto",
    "https://www.youtube.com/watch?v=9hLbsRU2neM",
    "https://www.youtube.com/watch?v=D938bjFYmII",
    "https://www.youtube.com/watch?v=bdapY46xR7A",
] * 2  # Duplicate to test deduplication

async def main():
    drizzler = RequestDrizzler(
        urls=URLS,
        per_host_rate=1.0,
        global_concurrency=5,
        request_timeout_s=30.0,
        max_retries=3,
        state_file="youtube_state.json",
        deduplicate=True,
        download_video=True,
        download_info=True,
        download_thumbnail=True,
        output_dir="./downloads",
    )
    stats = await drizzler.run()
    print(f"\n✅ Success: {stats.success}, Errors: {stats.errors}")

if __name__ == "__main__":
    asyncio.run(main())