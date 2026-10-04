import hashlib
import subprocess

import numpy as np
import pytest

from app.errors import ProcessingError
from app.jobs import create_job, read_json, update_job
from app.pipeline import process_job
from app.rendering.overlay import draw_overlay
from app.rendering.writer import OverlayWriter
from app.tracking.storage import read_records
from app.video.reader import frames, inspect_video
from tests.conftest import make_video, pose


class FakeEngine:
    metadata = {"engine": "test fixture", "configuration": {}}

    def __init__(self, settings):
        self.counter = 0

    def detect(self, rgb, timestamp_ms):
        self.counter += 1
        return [] if self.counter == 3 else pose(0.5 + 0.001 * (self.counter % 2))

    def close(self):
        pass


@pytest.mark.parametrize("fps,size,suffix", [(30, "160x120", ".mp4"), (60, "120x160", ".mov")])
def test_end_to_end_preserves_all_frames_and_original(settings, fps, size, suffix):
    job = create_job(settings, "exercise" + suffix)
    source = make_video(job / "input" / ("original" + suffix), fps=fps, size=size)
    digest = hashlib.sha256(source.read_bytes()).digest()
    update_job(job, original_path="input/" + source.name)
    process_job(job, settings, FakeEngine)
    status = read_json(job / "job.json")
    assert status["state"] == "complete"
    assert status["frames_processed"] == round(0.4 * fps)
    assert status["video"]["fps"] == fps
    assert hashlib.sha256(source.read_bytes()).digest() == digest
    raw = list(read_records(job / "tracking/raw.jsonl.gz"))
    smooth = list(read_records(job / "tracking/smoothed.jsonl.gz"))
    assert len(raw) == len(smooth) == status["frames_processed"]
    assert raw[2]["poses"] == smooth[2]["poses"] == []
    assert 6 <= len(status["gallery"]) <= 10
    for name in ("pose-overlay.mp4", "pose-overlay-raw.mp4"):
        video = inspect_video(job / "output" / name)
        assert video["codec"] == "h264"
        assert video["frame_count"] == len(raw)
        assert (video["width"], video["height"]) == tuple(map(int, size.split("x")))
        assert video["duration_s"] == pytest.approx(0.4, abs=0.02)


def test_rotated_phone_video(tmp_path):
    base = make_video(tmp_path / "base.mp4")
    rotated = tmp_path / "rotated.mov"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-display_rotation",
            "90",
            "-i",
            str(base),
            "-c",
            "copy",
            str(rotated),
        ],
        check=True,
    )
    metadata = inspect_video(rotated)
    assert metadata["orientation"] == "portrait"
    decoded = next(frames(rotated, metadata))[3]
    assert decoded.shape[:2] == (160, 120)
    upright = next(frames(base, inspect_video(base)))[3]
    assert np.array_equal(decoded, np.rot90(upright))


def test_variable_timestamps_survive_overlay_encoding(tmp_path):
    metadata = {"width": 160, "height": 120, "fps_fraction": "30"}
    writer = OverlayWriter(tmp_path / "variable.mp4", metadata)
    timestamps = [0, 0.033, 0.100, 0.117, 0.250]
    try:
        for t in timestamps:
            writer.write(np.zeros((120, 160, 3), dtype=np.uint8), t)
    finally:
        writer.close()
    actual = [
        r[1] for r in frames(tmp_path / "variable.mp4", inspect_video(tmp_path / "variable.mp4"))
    ]
    assert actual == pytest.approx(timestamps, abs=0.0001)


def test_overlay_only_draws_on_copy():
    source = np.zeros((120, 160, 3), dtype=np.uint8)
    output = draw_overlay(source, pose(), 0, 0, 0.95)
    assert np.count_nonzero(source) == 0
    assert np.count_nonzero(output) > 0
    assert np.array_equal(output[80:110, 0:20], source[80:110, 0:20])


def test_corrupt_video_clean_failure(tmp_path):
    source = tmp_path / "corrupt.mp4"
    source.write_bytes(b"not a video")
    with pytest.raises(ProcessingError, match="cannot be read"):
        inspect_video(source)


def test_missing_ffprobe_clean_failure(tmp_path, monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", missing)
    with pytest.raises(ProcessingError, match="FFmpeg/ffprobe is missing"):
        inspect_video(tmp_path / "video.mp4")


@pytest.mark.integration
def test_real_mediapipe_blank_video_keeps_low_quality_outputs(settings):
    if not settings.model_path.exists():
        pytest.skip("Run model setup first")
    job = create_job(settings, "blank.mp4")
    source = job / "input/original.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=black:size=160x120:rate=60",
            "-t",
            "0.15",
            "-c:v",
            "libx264",
            str(source),
        ],
        check=True,
    )
    update_job(job, original_path="input/original.mp4")
    process_job(job, settings)
    status = read_json(job / "job.json")
    assert status["state"] == "complete"
    assert status["quality"]["quality"] == "Low"
    assert status["frames_processed"] == 9
