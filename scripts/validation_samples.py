"""Download three public demonstrations for local validation, never private footage."""

import hashlib
import json
import subprocess
import urllib.parse
import urllib.request

from app.config import Settings

SAMPLES = [
    ("squat", "Squat - exercise demonstration video.webm", "FitnessScape", "CC BY 3.0", 30),
    ("pullups", "Pull-ups - exercise demonstration video.webm", "FitnessScape", "CC BY 3.0", 60),
    ("single-leg", "Basic single leg squat.webm", "RickyBennison", "CC BY-SA 4.0", 30),
]


def main():
    folder = Settings.from_env().data_dir / "validation-sources"
    folder.mkdir(parents=True, exist_ok=True)
    sources = []
    for name, filename, author, license_name, fps in SAMPLES:
        digest = hashlib.md5(filename.replace(" ", "_").encode()).hexdigest()
        url = (
            f"https://upload.wikimedia.org/wikipedia/commons/{digest[0]}/{digest[:2]}/"
            + urllib.parse.quote(filename.replace(" ", "_"))
        )
        original = folder / (name + ".webm")
        req = urllib.request.Request(url, headers={"User-Agent": "LinkoStage1Validation/0.1"})
        if not original.exists():
            with urllib.request.urlopen(req, timeout=60) as response:
                original.write_bytes(response.read())
        # Re-encode only for our supported upload containers. 60 FPS is a transport test,
        # not native 60 FPS motion detail; this is recorded in the validation report.
        target = folder / (name + (".mov" if name == "single-leg" else ".mp4"))
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-i",
                str(original),
                "-r",
                str(fps),
                "-c:v",
                "libx264",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-an",
                str(target),
            ],
            check=True,
        )
        sources.append(
            {
                "name": name,
                "path": str(target),
                "author": author,
                "license": license_name,
                "fps": fps,
                "download": url,
                "page": "https://commons.wikimedia.org/wiki/File:" + urllib.parse.quote(filename),
            }
        )
        print(target)
    (folder / "sources.json").write_text(json.dumps(sources, indent=2))


if __name__ == "__main__":
    main()
