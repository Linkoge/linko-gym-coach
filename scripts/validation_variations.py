"""Derive controlled stress clips from the public squat demo, not private recordings."""

import subprocess

from app.config import Settings

VARIATIONS = {
    "occlusion": "drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill:enable='between(t,2,2.8)'",
    "cropped": "crop=800:480:240:0",
    "edge": "crop=800:720:0:0",
    "dark": "eq=brightness=-0.35:contrast=0.65",
    "fast": "setpts=0.5*PTS,fps=60",
}


def main():
    folder = Settings.from_env().data_dir / "validation-sources"
    source = folder / "squat.mp4"
    if not source.exists():
        raise SystemExit("Run python -m scripts.validation_samples first")
    for name, graph in VARIATIONS.items():
        target = folder / ("stress-" + name + ".mp4")
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-i",
                str(source),
                "-vf",
                graph,
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
        print(target)


if __name__ == "__main__":
    main()
