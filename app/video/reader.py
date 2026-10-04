import json
import math
import subprocess
from fractions import Fraction

import av
import numpy as np

from app.errors import ProcessingError


def inspect_video(path):
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-protocol_whitelist",
                "file,pipe",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        data = json.loads(result.stdout)
        stream = next(s for s in data["streams"] if s["codec_type"] == "video")
        width, height = int(stream["width"]), int(stream["height"])
        fps = float(Fraction(stream.get("avg_frame_rate", "0/1")))
        if fps <= 0:
            fps = float(Fraction(stream.get("r_frame_rate", "0/1")))
        if not math.isfinite(fps) or not 0 < fps <= 240:
            raise ValueError("Invalid or unsupported frame rate")
        rotation = float(stream.get("tags", {}).get("rotate", 0))
        for side_data in stream.get("side_data_list", []):
            if "rotation" in side_data:
                rotation = float(side_data["rotation"])
        rotation = rotation % 360
        if rotation not in (0, 90, 180, 270):
            raise ProcessingError(
                "Unsupported arbitrary video rotation. Export at 0/90/180/270 degrees."
            )
        # Fail explicitly on non-square samples instead of distorting pixels.
        sar = stream.get("sample_aspect_ratio", "1:1")
        if sar not in ("1:1", "0:1", "N/A"):
            raise ProcessingError(
                "Non-square video pixels are unsupported. Export with square pixels."
            )
        display_width, display_height = (
            (height, width) if rotation in (90, 270) else (width, height)
        )
        if width <= 0 or height <= 0 or width * height > 3840 * 2160 * 2:
            raise ProcessingError("Video dimensions are unsupported; export at 4K or lower.")
        duration = float(stream.get("duration", data["format"].get("duration", 0)))
        count = stream.get("nb_frames")
        return {
            "coded_width": width,
            "coded_height": height,
            "width": display_width,
            "height": display_height,
            "fps": fps,
            "fps_fraction": str(Fraction(fps).limit_denominator(100001)),
            "duration_s": duration,
            "frame_count": int(count) if count and count != "N/A" else None,
            "frame_count_estimate": round(duration * fps),
            "rotation_degrees": rotation,
            "orientation": "portrait"
            if display_height > display_width
            else "landscape"
            if display_width > display_height
            else "square",
            "codec": stream.get("codec_name"),
            "container": data["format"].get("format_name"),
            "has_audio": any(s["codec_type"] == "audio" for s in data["streams"]),
            "warnings": (
                ["Overlay videos are silent; audio remains in the original."]
                if any(s["codec_type"] == "audio" for s in data["streams"])
                else []
            ),
        }
    except ProcessingError:
        raise
    except (ValueError, KeyError, StopIteration, subprocess.SubprocessError) as exc:
        raise ProcessingError(
            "The file cannot be read as a supported video. Try exporting an MP4 with H.264 video."
        ) from exc
    except FileNotFoundError as exc:
        raise ProcessingError(
            "FFmpeg/ffprobe is missing. Install FFmpeg before processing."
        ) from exc


def frames(path, metadata):
    """Use presentation timestamps, not frame/FPS approximations. Rotate exactly once."""
    origin = None
    previous = -1.0
    with av.open(str(path), options={"protocol_whitelist": "file,pipe"}) as container:
        for index, frame in enumerate(container.decode(video=0)):
            source_time = frame.time
            if source_time is None:
                timestamp = index / metadata["fps"]
            else:
                if origin is None:
                    origin = source_time
                timestamp = source_time - origin
            if timestamp <= previous:
                raise ProcessingError(
                    "Video timestamps are non-monotonic. Re-export the video as MP4."
                )
            previous = timestamp
            rgb = frame.to_ndarray(format="rgb24")
            rotation = metadata["rotation_degrees"]
            if rotation:
                rgb = np.rot90(rgb, k=int(rotation / 90))
            yield index, timestamp, source_time, np.ascontiguousarray(rgb)
