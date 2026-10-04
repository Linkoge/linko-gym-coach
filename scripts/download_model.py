"""Explicit setup download; processing never downloads or uploads user data."""

import hashlib
import os
import urllib.request

from app.config import Settings

URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_heavy/float16/1/pose_landmarker_heavy.task"
)
SHA256 = "64437af838a65d18e5ba7a0d39b465540069bc8aae8308de3e318aad31fcbc7b"


def main():
    path = Settings.from_env().model_path
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".download")
    try:
        with urllib.request.urlopen(URL, timeout=120) as response, temp.open("wb") as out:
            while block := response.read(1024 * 1024):
                out.write(block)
        if temp.stat().st_size < 10_000_000:
            raise RuntimeError("Downloaded model is unexpectedly small")
        if hashlib.sha256(temp.read_bytes()).hexdigest() != SHA256:
            raise RuntimeError(
                "Downloaded model checksum does not match the pinned Heavy v1 bundle"
            )
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    print(f"Model: {path}\nSHA-256: {hashlib.sha256(path.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
