import asyncio
import sys
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.errors import ProcessingError
from app.jobs import cleanup_jobs, create_job, read_json, require_disk, update_job
from app.supervisor import Supervisor
from app.web.main import create_app


def test_upload_status_download_and_traversal(settings):
    with TestClient(create_app(settings, run_workers=False)) as client:
        response = client.post("/api/jobs?filename=workout.MOV", content=b"fixture")
        assert response.status_code == 202
        job_id = response.json()["id"]
        job = client.get("/api/jobs/" + job_id).json()
        assert job["state"] == "queued"
        base = f"/api/jobs/{job_id}/files/"
        assert client.get(base + "input/original.mov").content == b"fixture"
        assert client.get(base + "tracking/raw.jsonl.gz").status_code == 404
        assert client.get(base + "diagnostic.log").status_code == 404
        assert client.get(base + "tracking/../../job.json").status_code == 404
        assert client.get("/api/jobs/not-a-uuid").status_code == 404
        assert client.get("/").headers["cache-control"] == "no-store"
        assert client.get("/", headers={"Host": "attacker.example"}).status_code == 400


def test_upload_invalid_empty_oversize_cross_origin_and_disk(settings):
    with TestClient(create_app(replace(settings, max_upload_bytes=8), False)) as client:
        assert client.post("/api/jobs?filename=x.exe", content=b"data").status_code == 415
        assert client.post("/api/jobs?filename=x.mp4", content=b"").status_code == 400
        assert client.post("/api/jobs?filename=x.mp4", content=b"012345678").status_code == 413
        assert (
            client.post(
                "/api/jobs?filename=x.mp4", content=b"x", headers={"Origin": "https://example.com"}
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/jobs?filename=x.mp4", content=b"x", headers={"Origin": "http://testserver"}
            ).status_code
            == 202
        )
    with TestClient(create_app(replace(settings, min_free_bytes=10**18), False)) as client:
        response = client.post("/api/jobs?filename=x.mp4", content=b"x")
        assert response.status_code == 507
        assert "disk space" in response.json()["detail"]


def test_disk_check(settings, tmp_path):
    with pytest.raises(ProcessingError, match="disk space"):
        require_disk(replace(settings, min_free_bytes=10**18), tmp_path)


def test_tailscale_host_and_same_origin_upload(settings):
    configured = replace(settings, allowed_hosts="127.0.0.1,localhost,100.97.154.71")
    with TestClient(create_app(configured, False), base_url="http://100.97.154.71:8000") as client:
        assert client.get("/").status_code == 200
        assert client.get("/", headers={"Host": "attacker.example"}).status_code == 400
        assert (
            client.post(
                "/api/jobs?filename=x.mp4",
                content=b"x",
                headers={"Origin": "http://100.97.154.71:8000"},
            ).status_code
            == 202
        )
        assert (
            client.post(
                "/api/jobs?filename=x.mp4",
                content=b"x",
                headers={"Origin": "http://attacker.example"},
            ).status_code
            == 403
        )


def test_completed_files_support_browser_byte_ranges(settings):
    job = create_job(settings, "fixture.mp4")
    artifact = job / "output/pose-overlay.mp4"
    artifact.write_bytes(b"0123456789")
    update_job(job, state="complete")
    with TestClient(create_app(settings, False)) as client:
        response = client.get(
            f"/api/jobs/{job.name}/files/output/pose-overlay.mp4", headers={"Range": "bytes=2-5"}
        )
        assert response.status_code == 206
        assert response.content == b"2345"
        assert response.headers["content-range"] == "bytes 2-5/10"


def test_cleanup_disabled_by_default_and_protects_active(settings):
    old = create_job(settings, "old.mp4")
    active = create_job(settings, "active.mp4")
    update_job(old, state="complete")
    future = time.time() + 86400 * 5
    assert cleanup_jobs(settings, now=future, dry_run=False) == []
    retention = replace(settings, retention_days=1)
    assert cleanup_jobs(retention, now=future) == [old.name]
    assert old.exists()
    assert cleanup_jobs(retention, now=future, dry_run=False) == [old.name]
    assert not old.exists() and active.exists()


def test_restart_recovers_processing_but_retains_queued(settings):
    broken = create_job(settings, "broken.mp4")
    queued = create_job(settings, "queued.mp4")
    update_job(broken, state="processing")
    update_job(queued, state="queued")

    async def run():
        supervisor = Supervisor(settings)
        await supervisor.start()
        assert read_json(broken / "job.json")["state"] == "failed"
        assert read_json(queued / "job.json")["state"] == "queued"
        await supervisor.stop()

    asyncio.run(run())


@pytest.mark.parametrize("command", ["import os; os._exit(19)", "import time; time.sleep(20)"])
def test_supervisor_handles_crashed_and_stalled_workers(settings, monkeypatch, command):
    settings = replace(settings, worker_stall_seconds=0.1)
    job = create_job(settings, "fixture.mp4")
    update_job(job, state="queued")
    original_spawn = asyncio.create_subprocess_exec

    async def spawn(*args, **kwargs):
        return await original_spawn(sys.executable, "-c", command, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)

    async def run():
        supervisor = Supervisor(settings)
        await supervisor.start()
        try:
            for _ in range(120):
                await asyncio.sleep(0.05)
                state = read_json(job / "job.json")
                if state["state"] == "failed":
                    assert "Traceback" not in state["error"]
                    break
            else:
                pytest.fail("Supervisor did not handle worker failure")
        finally:
            await supervisor.stop()

    asyncio.run(run())
