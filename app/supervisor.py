import asyncio
import contextlib
import fcntl
import logging
import os
import signal
import sys
import time

from app.config import ROOT
from app.jobs import TERMINAL, cleanup_jobs, read_json, update_job

logger = logging.getLogger(__name__)


class Supervisor:
    """One durable local queue, one isolated worker. No Redis or external service."""

    def __init__(self, settings):
        self.settings = settings
        self.task = None
        self.process = None
        self.current = None
        self.lock = None

    async def start(self):
        self.settings.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = (self.settings.data_dir / ".server.lock").open("w")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            raise RuntimeError(
                "Another Linko server owns this data directory. Use one Uvicorn worker."
            ) from None
        for path in (self.settings.data_dir / "jobs").glob("*/job.json"):
            status = read_json(path)
            if status["state"] in ("processing", "uploading"):
                update_job(
                    path.parent,
                    state="failed",
                    stage="Interrupted",
                    error="The application stopped during this job. Upload the video again.",
                )
        self.task = asyncio.create_task(self.run())

    async def run(self):
        last_cleanup = 0
        while True:
            if time.time() - last_cleanup > 3600:
                cleanup_jobs(self.settings, dry_run=False)
                last_cleanup = time.time()
            queued = []
            for path in (self.settings.data_dir / "jobs").glob("*/job.json"):
                status = read_json(path)
                if status["state"] == "queued":
                    queued.append((status["created_at"], path.parent))
            if not queued:
                await asyncio.sleep(0.5)
                continue
            _, job = min(queued)
            self.current = job
            update_job(job, state="processing", stage="Starting worker", progress=0)
            environment = os.environ.copy()
            environment["LINKO_PARENT_PID"] = str(os.getpid())
            environment.update(
                {"LINKO_" + k.upper(): str(v) for k, v in self.settings.serializable().items()}
            )
            try:
                with (job / "worker.log").open("ab") as log:
                    self.process = await asyncio.create_subprocess_exec(
                        sys.executable,
                        "-m",
                        "app.worker",
                        job.name,
                        cwd=ROOT,
                        env=environment,
                        stdout=log,
                        stderr=log,
                        start_new_session=True,
                    )
                    while self.process.returncode is None:
                        try:
                            await asyncio.wait_for(self.process.wait(), timeout=2)
                        except TimeoutError:
                            status = read_json(job / "job.json")
                            if (
                                time.time() - status["updated_at"]
                                > self.settings.worker_stall_seconds
                            ):
                                os.killpg(self.process.pid, signal.SIGKILL)
                                await self.process.wait()
                                update_job(
                                    job,
                                    state="failed",
                                    stage="Failed",
                                    error="The worker stopped making progress and was terminated. "
                                    "Check the local logs and retry.",
                                )
                    status = read_json(job / "job.json")
                    if status["state"] not in TERMINAL:
                        update_job(
                            job,
                            state="failed",
                            stage="Failed",
                            error="The processing worker exited unexpectedly. "
                            "Check the local worker log and retry.",
                        )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Unable to start processing worker")
                update_job(
                    job,
                    state="failed",
                    stage="Failed",
                    error="The processing worker could not start. Check local server logs.",
                )
            finally:
                self.process = None
                self.current = None

    async def stop(self):
        # Terminate before cancellation clears the current process reference.
        if self.process and self.process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(self.process.pid, signal.SIGKILL)
            await self.process.wait()
            if self.current:
                update_job(
                    self.current,
                    state="failed",
                    stage="Interrupted",
                    error="The server stopped during processing. Upload the video again.",
                )
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
        if self.lock:
            self.lock.close()
