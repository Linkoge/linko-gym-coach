import json
import os
import shutil
import time
import uuid
from pathlib import Path

from app.errors import ProcessingError

TERMINAL = {"complete", "failed"}


def write_json(path: Path, value):
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w") as file:
        json.dump(value, file, indent=2, allow_nan=False)
    os.replace(temp, path)


def read_json(path: Path):
    return json.loads(path.read_text())


def create_job(settings, filename):
    job_id = str(uuid.uuid4())
    job = settings.data_dir / "jobs" / job_id
    for directory in ("input", "tracking", "output", "keyframes"):
        (job / directory).mkdir(parents=True, exist_ok=True, mode=0o700)
    update_job(
        job,
        id=job_id,
        filename=filename,
        state="uploading",
        stage="Uploading",
        progress=0,
        created_at=time.time(),
        frames_processed=0,
    )
    return job


def update_job(job, **changes):
    path = job / "job.json"
    status = read_json(path) if path.exists() else {}
    status.update(changes)
    status["updated_at"] = time.time()
    write_json(path, status)
    return status


def job_path(settings, job_id):
    try:
        if str(uuid.UUID(job_id)) != job_id:
            raise ValueError
    except ValueError:
        raise ProcessingError("Job not found") from None
    path = settings.data_dir / "jobs" / job_id
    if not (path / "job.json").is_file():
        raise ProcessingError("Job not found")
    return path


def require_disk(settings, directory, extra=0):
    if shutil.disk_usage(directory).free < settings.min_free_bytes + extra:
        raise ProcessingError("Insufficient disk space. Free space and upload the video again.")


def cleanup_jobs(settings, now=None, dry_run=True):
    """Only terminal jobs are eligible. Cleanup is disabled unless retention > 0."""
    if settings.retention_days <= 0:
        return []
    cutoff = (now or time.time()) - settings.retention_days * 86400
    selected = []
    for status_file in (settings.data_dir / "jobs").glob("*/job.json"):
        status = read_json(status_file)
        if status["state"] in TERMINAL and status["updated_at"] < cutoff:
            selected.append(status["id"])
            if not dry_run:
                shutil.rmtree(status_file.parent)
    return selected
