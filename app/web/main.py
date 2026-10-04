import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import Settings
from app.errors import ProcessingError
from app.jobs import create_job, job_path, read_json, require_disk, update_job
from app.supervisor import Supervisor

STATIC = Path(__file__).parent / "static"


def create_app(settings=None, run_workers=True):
    settings = settings or Settings.from_env()
    supervisor = Supervisor(settings)

    @asynccontextmanager
    async def lifespan(app):
        os.umask(0o077)
        settings.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        if run_workers:
            await supervisor.start()
        try:
            yield
        finally:
            if run_workers:
                await supervisor.stop()

    app = FastAPI(
        title="Linko Gym Coach — Stage 1", lifespan=lifespan, docs_url=None, redoc_url=None
    )
    app.state.settings = settings
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=[host.strip() for host in settings.allowed_hosts.split(",") if host.strip()],
    )

    @app.middleware("http")
    async def local_privacy(request, call_next):
        origin = request.headers.get("origin")
        if request.method == "POST" and origin:
            if urlsplit(origin).netloc != request.headers.get("host"):
                return JSONResponse(
                    {"detail": "Cross-origin uploads are not allowed."}, status_code=403
                )
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; media-src 'self'; "
            "style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
        )
        return response

    @app.exception_handler(ProcessingError)
    async def handle_processing_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.get("/")
    @app.get("/jobs/{job_id}")
    async def index(job_id: str | None = None):
        if job_id:
            job_path(settings, job_id)
        return FileResponse(STATIC / "index.html")

    @app.post("/api/jobs", status_code=202)
    async def upload(request: Request, filename: str):
        filename = Path(filename.replace("\\", "/")).name
        extension = Path(filename).suffix.lower()
        if extension not in {".mp4", ".mov"}:
            raise HTTPException(415, "Select an MP4 or MOV video.")
        if len(filename) > 255 or not filename:
            raise HTTPException(400, "Invalid filename.")
        declared = request.headers.get("content-length")
        if declared:
            try:
                length = int(declared)
            except ValueError:
                raise HTTPException(400, "Invalid upload size.") from None
            if length > settings.max_upload_bytes:
                raise HTTPException(413, "Video exceeds the configured upload limit.")
        job = create_job(settings, filename)
        destination = job / "input" / ("original" + extension)
        total = 0
        try:
            with destination.open("wb") as file:
                async for chunk in request.stream():
                    total += len(chunk)
                    if total > settings.max_upload_bytes:
                        raise HTTPException(413, "Video exceeds the configured upload limit.")
                    require_disk(settings, job, len(chunk))
                    file.write(chunk)
            if not total:
                raise HTTPException(400, "The selected video is empty.")
            update_job(
                job,
                state="queued",
                stage="Queued",
                upload_bytes=total,
                original_path="input/" + destination.name,
            )
        except BaseException as exc:
            destination.unlink(missing_ok=True)
            message = (
                str(exc)
                if isinstance(exc, ProcessingError)
                else "Upload was interrupted or failed."
            )
            update_job(job, state="failed", stage="Upload failed", error=message)
            if isinstance(exc, ProcessingError):
                raise HTTPException(507, message) from None
            if isinstance(exc, OSError):
                raise HTTPException(
                    507, "Upload could not be saved. Check available disk space."
                ) from None
            raise
        return {"id": job.name, "url": "/jobs/" + job.name}

    @app.get("/api/jobs/{job_id}")
    async def status(job_id: str):
        return read_json(job_path(settings, job_id) / "job.json")

    @app.get("/api/jobs/{job_id}/files/{relative_path:path}")
    async def download(job_id: str, relative_path: str):
        job = job_path(settings, job_id)
        status = read_json(job / "job.json")
        allowed = {status.get("original_path")}
        if status["state"] == "complete":
            allowed.update(
                {
                    "output/pose-overlay.mp4",
                    "output/pose-overlay-raw.mp4",
                    "tracking/raw.jsonl.gz",
                    "tracking/smoothed.jsonl.gz",
                    "tracking/quality.json",
                    "tracking/schema.json",
                    "tracking/events.jsonl.gz",
                    "tracking/metrics.sqlite3",
                    "video.json",
                }
            )
            for item in status.get("gallery", []):
                allowed.update(item[k] for k in ("original", "raw", "smoothed"))
        if relative_path not in allowed:
            raise HTTPException(404, "File not found or job not complete.")
        path = job / relative_path
        if not path.is_file():
            raise HTTPException(404, "File is no longer available.")
        inline = path.suffix in {".mp4", ".mov", ".jpg"}
        return FileResponse(
            path,
            filename=None if inline else path.name,
            media_type="video/mp4" if path.suffix == ".mp4" else None,
        )

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


app = create_app()
