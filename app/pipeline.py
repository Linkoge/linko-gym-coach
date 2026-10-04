import logging
import time
from contextlib import ExitStack

from app.errors import ProcessingError
from app.jobs import read_json, require_disk, update_job, write_json
from app.pose.mediapipe_engine import MediaPipeEngine
from app.rendering.overlay import draw_overlay
from app.rendering.writer import OverlayWriter
from app.reports.keyframes import create_gallery
from app.tracking.quality import QualityTracker
from app.tracking.smoothing import PoseSmoother
from app.tracking.storage import PoseWriter, read_records
from app.video.reader import frames, inspect_video

logger = logging.getLogger(__name__)


def process_job(job, settings, engine_factory=MediaPipeEngine):
    started = time.monotonic()
    source = job / read_json(job / "job.json")["original_path"]
    update_job(job, state="processing", stage="Reading video", progress=0.01)
    metadata = inspect_video(source)
    if metadata["width"] % 2 or metadata["height"] % 2:
        metadata["warnings"].append(
            "Odd video dimensions require H.264 yuv444p; "
            "some phone/browser players may not support the overlays."
        )
    write_json(job / "video.json", metadata)
    estimate = metadata["frame_count"] or metadata["frame_count_estimate"] or 1
    require_disk(settings, job)
    update_job(job, video=metadata, stage="Tracking pose", progress=0.02)
    last_update = 0.0

    def progress(stage, processed, base, span, total=estimate):
        nonlocal last_update
        now = time.monotonic()
        if now - last_update >= 1:
            require_disk(settings, job)
            update_job(
                job,
                stage=stage,
                progress=min(base + span * processed / max(total, 1), base + span),
                frames_processed=processed if stage == "Tracking pose" else count,
            )
            last_update = now

    count, last_timestamp, previous_ms, timestamp_adjustments = 0, 0.0, -1, 0
    with ExitStack() as stack:
        engine = engine_factory(settings)
        stack.callback(engine.close)
        raw = PoseWriter(job / "tracking/raw.jsonl.gz")
        stack.callback(raw.close)
        smooth = PoseWriter(job / "tracking/smoothed.jsonl.gz")
        stack.callback(smooth.close)
        quality = QualityTracker(job / "tracking", settings)
        stack.callback(quality.close)
        smoother = PoseSmoother(settings)
        write_json(
            job / "tracking/schema.json",
            {
                "schema_version": 1,
                "format": "gzip-compressed JSON Lines; one record per decoded frame",
                "frame_number": "zero based",
                "timestamp_s": "presentation time relative to first frame",
                "source_timestamp_s": "original presentation timestamp when available",
                "coordinate_frame": "upright display orientation; x right, y down",
                "normalized": "x/width, y/height; z in approximate image-width units at hips",
                "world": "estimated meters, origin midpoint of hips; not calibrated",
                "missing": "null fields remain null; poses=[] means no detection; no interpolation",
                "pose_index": "frame-local result order; NOT a persistent person identity",
                "raw": "unmodified estimator coordinates/confidences; may be internally smoothed",
                "smoothing": {
                    "algorithm": "One Euro",
                    "min_cutoff_hz": settings.min_cutoff,
                    "beta": settings.beta,
                    "derivative_cutoff_hz": settings.derivative_cutoff,
                    "reset_gap_seconds": settings.reset_gap_seconds,
                    "low_confidence": "bypass and reset",
                    "multiple_poses": "bypass and reset",
                    "jump": "bypass and reset",
                },
                "estimator": engine.metadata,
            },
        )
        for index, timestamp, source_timestamp, rgb in frames(source, metadata):
            timestamp_ms = max(previous_ms + 1, round(timestamp * 1000))
            timestamp_adjustments += timestamp_ms != round(timestamp * 1000)
            previous_ms = timestamp_ms
            poses = engine.detect(rgb, timestamp_ms)
            record = {
                "schema_version": 1,
                "frame_number": index,
                "timestamp_s": timestamp,
                "source_timestamp_s": source_timestamp,
                "estimator_timestamp_ms": timestamp_ms,
                "poses": poses,
            }
            raw.write(record)
            smooth.write({**record, "poses": smoother.apply(poses, timestamp)})
            quality.add(record)
            count, last_timestamp = index + 1, timestamp
            progress("Tracking pose", count, 0.02, 0.58)
        if not count:
            raise ProcessingError("The video contains no decodable frames.")
        report = quality.finish(last_timestamp + 1 / metadata["fps"])
        report["video"] = metadata
        report["estimator"] = engine.metadata
        report["estimator_timestamp_adjustments"] = timestamp_adjustments
        # Container frame counts can be absent or inaccurate; expose actual decoded count.
        if metadata["frame_count"] is not None and count < metadata["frame_count"]:
            raise ProcessingError(
                "The video ended before all declared frames could be decoded. "
                "The file may be truncated; export it again."
            )
        metadata["decoded_frame_count"] = count
        metadata["decoded_duration_s"] = last_timestamp + 1 / metadata["fps"]
        write_json(job / "video.json", metadata)
        write_json(job / "tracking/quality.json", report)

    update_job(job, stage="Creating overlay", progress=0.61, frames_processed=count, video=metadata)
    with ExitStack() as stack:
        writers = {}
        for kind, name in (("raw", "pose-overlay-raw.mp4"), ("smoothed", "pose-overlay.mp4")):
            writer = OverlayWriter(job / "output" / name, metadata)
            stack.callback(writer.close)
            writers[kind] = writer
        for (index, timestamp, _, rgb), raw_record, smooth_record in zip(
            frames(source, metadata),
            read_records(job / "tracking/raw.jsonl.gz"),
            read_records(job / "tracking/smoothed.jsonl.gz"),
            strict=True,
        ):
            from app.pose.schema import confidence

            cs = [confidence(lm) for pose in raw_record["poses"] for lm in pose["landmarks"]]
            mean = sum(cs) / len(cs) if cs else 0
            for kind, record in (("raw", raw_record), ("smoothed", smooth_record)):
                overlay = draw_overlay(
                    rgb,
                    record["poses"],
                    index,
                    timestamp,
                    mean,
                    kind,
                    settings.confidence_threshold,
                )
                writers[kind].write(overlay, timestamp)
            progress("Creating overlay", index + 1, 0.61, 0.28, count)

    update_job(job, stage="Creating verification gallery", progress=0.90)
    gallery = create_gallery(
        job,
        source,
        metadata,
        count,
        settings,
        lambda index: progress("Creating verification gallery", index, 0.90, 0.09, count),
    )
    report["processing_seconds"] = time.monotonic() - started
    write_json(job / "tracking/quality.json", report)
    update_job(
        job,
        state="complete",
        stage="Complete",
        progress=1,
        quality=report,
        gallery=gallery,
        frames_processed=count,
        processing_seconds=report["processing_seconds"],
    )
