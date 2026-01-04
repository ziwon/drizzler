import uuid
import os
import shutil
import asyncio
import logging
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field
from datetime import datetime, timedelta

from drizzler.core import RequestDrizzler

logger = logging.getLogger(__name__)

class VideoProgress(BaseModel):
    """Video download progress details"""
    downloaded_bytes: float = 0
    total_bytes: float = 0
    speed: str = ""  # e.g., "12.5 MB/s"
    eta: str = ""    # e.g., "00:28"
    percent: float = 0.0

class JobStatus(BaseModel):
    id: str
    status: str  # "pending", "running", "completed", "failed"
    progress: float = 0.0
    current_stage: str = ""  # "Downloading metadata", "Downloading video", "Generating summary", etc.
    video_progress: Optional[VideoProgress] = None  # Detailed video download progress
    video_title: str = ""  # Video title from yt-dlp
    video_thumbnail: str = ""  # Thumbnail URL from yt-dlp
    urls: List[str]
    created_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    output_dir: str
    files: List[str] = []
    error: Optional[str] = None

class JobManager:
    def __init__(self, base_output_dir: str = "downloads/jobs"):
        self.base_output_dir = base_output_dir
        self.jobs: Dict[str, JobStatus] = {}
        os.makedirs(self.base_output_dir, exist_ok=True)
        # Start cleanup task
        asyncio.create_task(self._cleanup_loop())

    def create_job(self, urls: List[str], options: Dict[str, Any]) -> str:
        job_id = str(uuid.uuid4())
        job_dir = os.path.join(self.base_output_dir, job_id)
        os.makedirs(job_dir, exist_ok=True)

        job = JobStatus(
            id=job_id,
            status="pending",
            urls=urls,
            output_dir=job_dir,
            current_stage="Initializing..."
        )
        self.jobs[job_id] = job

        # Start job in background
        asyncio.create_task(self._run_job(job_id, options))
        return job_id

    async def _run_job(self, job_id: str, options: Dict[str, Any]):
        job = self.jobs[job_id]
        job.status = "running"
        job.current_stage = "Starting..."

        def progress_callback(completed, total, worker_id):
            job.progress = (completed / total) * 100 if total > 0 else 0

        def stage_callback(stage: str, video_info: Optional[Dict] = None):
            """Callback for stage updates"""
            job.current_stage = stage
            if video_info:
                # Handle video download progress
                if "downloaded_bytes" in video_info:
                    job.video_progress = VideoProgress(
                        downloaded_bytes=video_info.get("downloaded_bytes", 0),
                        total_bytes=video_info.get("total_bytes", 0),
                        speed=video_info.get("speed", ""),
                        eta=video_info.get("eta", ""),
                        percent=video_info.get("percent", 0.0)
                    )
                # Handle video metadata (title, thumbnail)
                if "title" in video_info:
                    job.video_title = video_info.get("title", "")
                if "thumbnail" in video_info:
                    job.video_thumbnail = video_info.get("thumbnail", "")
            else:
                job.video_progress = None

        try:
            drizzler = RequestDrizzler(
                urls=job.urls,
                output_dir=job.output_dir,
                progress_callback=progress_callback,
                stage_callback=stage_callback,
                **options
            )
            await drizzler.run()

            # List files
            files = []
            for root, _, filenames in os.walk(job.output_dir):
                for filename in filenames:
                    rel_path = os.path.relpath(os.path.join(root, filename), job.output_dir)
                    files.append(rel_path)

            job.files = files
            job.status = "completed"
            job.progress = 100.0
            job.current_stage = "Completed"
            job.video_progress = None
            job.completed_at = datetime.now()

        except Exception as e:
            logger.error(f"Job {job_id} failed: {e}")
            job.status = "failed"
            job.error = str(e)
            job.current_stage = "Failed"
            job.video_progress = None

    def get_job(self, job_id: str) -> Optional[JobStatus]:
        return self.jobs.get(job_id)

    def list_jobs(self) -> List[JobStatus]:
        return sorted(self.jobs.values(), key=lambda x: x.created_at, reverse=True)

    def delete_job(self, job_id: str):
        if job_id in self.jobs:
            job = self.jobs[job_id]
            if os.path.exists(job.output_dir):
                shutil.rmtree(job.output_dir)
            del self.jobs[job_id]

    async def _cleanup_loop(self):
        """Periodically clean up old jobs."""
        while True:
            await asyncio.sleep(3600)  # Check every hour
            now = datetime.now()
            jobs_to_delete = []
            for job_id, job in self.jobs.items():
                if now - job.created_at > timedelta(hours=24):
                    jobs_to_delete.append(job_id)

            for job_id in jobs_to_delete:
                logger.info(f"Cleaning up old job: {job_id}")
                self.delete_job(job_id)
