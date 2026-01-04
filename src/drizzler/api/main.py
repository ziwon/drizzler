import os
from typing import List, Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from drizzler.api.jobs import JobManager, JobStatus

app = FastAPI(title="Drizzler API", description="API for adaptive HTTP fetching and YouTube downloading")

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

job_manager = JobManager()

class JobCreate(BaseModel):
    urls: List[str]
    write_video: bool = False
    write_info_json: bool = False
    write_thumbnail: bool = False
    write_subs: bool = False
    write_txt: bool = False
    summarize: bool = False
    summary_lang: str = "en"  # en, ko, ja
    rate: float = 1.0
    concurrency: int = 5
    llm_provider: str = "openai"
    llm_model: str = ""

@app.post("/api/jobs", response_model=dict)
async def create_job(request: JobCreate):
    options = {
        "download_video": request.write_video,
        "download_info": request.write_info_json,
        "download_thumbnail": request.write_thumbnail,
        "download_subs": request.write_subs,
        "download_txt": request.write_txt,
        "summarize": request.summarize,
        "summary_lang": request.summary_lang,
        "per_host_rate": request.rate,
        "global_concurrency": request.concurrency,
        "llm_provider": request.llm_provider,
        "llm_model": request.llm_model,
        "use_progress_bar": False, # Disable rich progress bar in API
    }
    job_id = job_manager.create_job(request.urls, options)
    return {"job_id": job_id}

@app.get("/api/jobs", response_model=List[JobStatus])
async def list_jobs():
    return job_manager.list_jobs()

@app.get("/api/jobs/{job_id}", response_model=JobStatus)
async def get_job(job_id: str):
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job

@app.get("/api/jobs/{job_id}/files/{file_path:path}")
async def get_job_file(job_id: str, file_path: str):
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    full_path = os.path.join(job.output_dir, file_path)
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(full_path)

@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str):
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job_manager.delete_job(job_id)
    return {"status": "deleted"}

# Serve static files from the React app
ui_dist_path = "ui/dist"
if os.path.exists(ui_dist_path):
    app.mount("/", StaticFiles(directory=ui_dist_path, html=True), name="ui")
else:
    @app.get("/")
    async def read_root():
        return {"message": "Drizzler API is running. UI dist folder not found."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
