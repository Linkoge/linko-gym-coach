import copy
import subprocess
from dataclasses import replace

import pytest

from app.config import Settings
from app.pose.schema import NAMES


@pytest.fixture
def settings(tmp_path):
    return replace(Settings(), data_dir=tmp_path / "data", min_free_bytes=0)


def pose(x=0.5, visibility=0.95, presence=0.98):
    return [
        {
            "pose_index": 0,
            "landmarks": [
                {
                    "id": i,
                    "name": name,
                    "x": x,
                    "y": 0.5,
                    "z": 0.0,
                    "visibility": visibility,
                    "presence": presence,
                    "world": {
                        "x": 0.0,
                        "y": 0.0,
                        "z": 0.0,
                        "visibility": visibility,
                        "presence": presence,
                    },
                }
                for i, name in enumerate(NAMES)
            ],
        }
    ]


def record(frame, poses, fps=30):
    return {"frame_number": frame, "timestamp_s": frame / fps, "poses": copy.deepcopy(poses)}


def make_video(path, fps=30, size="160x120", duration=0.4):
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size={size}:rate={fps}",
            "-t",
            str(duration),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
    )
    return path
