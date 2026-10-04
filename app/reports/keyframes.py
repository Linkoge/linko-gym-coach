import sqlite3

import cv2

from app.errors import ProcessingError
from app.jobs import write_json
from app.rendering.overlay import draw_overlay
from app.tracking.storage import read_records
from app.video.reader import frames


def select_frames(database, count):
    selected = {}

    def add(frame, reason):
        if frame is not None and 0 <= frame < count:
            selected.setdefault(frame, []).append(reason)

    # Six distributed anchors plus confidence/motion/anomaly examples, at most ten unique frames.
    for fraction, label in zip(
        (0, 0.2, 0.4, 0.6, 0.8, 1), ("Early", "20%", "40%", "60%", "80%", "Late"), strict=True
    ):
        add(round((count - 1) * fraction), label)
    with sqlite3.connect(database) as db:
        for query, label in (
            (
                "SELECT frame FROM frames WHERE detected=1 ORDER BY confidence DESC, frame LIMIT 1",
                "Highest confidence",
            ),
            ("SELECT frame FROM frames ORDER BY confidence, frame LIMIT 1", "Lowest confidence"),
            (
                "SELECT frame FROM frames ORDER BY movement DESC, frame LIMIT 1",
                "Largest observed movement",
            ),
            (
                "SELECT frame FROM frames WHERE anomaly=1 ORDER BY confidence, frame LIMIT 1",
                "Tracking anomaly",
            ),
        ):
            row = db.execute(query).fetchone()
            if row:
                add(row[0], label)
    return selected


def create_gallery(job, source, metadata, count, settings, progress):
    selected = select_frames(job / "tracking/metrics.sqlite3", count)
    raw = read_records(job / "tracking/raw.jsonl.gz")
    smooth = read_records(job / "tracking/smoothed.jsonl.gz")
    items = []
    for (index, timestamp, _, rgb), raw_record, smooth_record in zip(
        frames(source, metadata), raw, smooth, strict=True
    ):
        if index % 100 == 0:
            progress(index)
        if index not in selected:
            continue
        confidences = [
            min(lm[k] for k in ("visibility", "presence") if lm[k] is not None)
            if any(lm[k] is not None for k in ("visibility", "presence"))
            else 0
            for pose in raw_record["poses"]
            for lm in pose["landmarks"]
        ]
        mean = sum(confidences) / len(confidences) if confidences else 0
        names = {}
        for kind, image in (
            ("original", rgb),
            (
                "raw",
                draw_overlay(
                    rgb,
                    raw_record["poses"],
                    index,
                    timestamp,
                    mean,
                    "raw",
                    settings.confidence_threshold,
                ),
            ),
            (
                "smoothed",
                draw_overlay(
                    rgb,
                    smooth_record["poses"],
                    index,
                    timestamp,
                    mean,
                    "smoothed",
                    settings.confidence_threshold,
                ),
            ),
        ):
            name = f"frame-{index:06d}-{kind}.jpg"
            if not cv2.imwrite(
                str(job / "keyframes" / name),
                cv2.cvtColor(image, cv2.COLOR_RGB2BGR),
                [cv2.IMWRITE_JPEG_QUALITY, 95],
            ):
                raise ProcessingError(
                    "Could not write verification images. Check available disk space."
                )
            names[kind] = "keyframes/" + name
        items.append(
            {
                "frame_number": index,
                "timestamp_s": timestamp,
                "confidence": mean,
                "reasons": selected[index],
                **names,
            }
        )
    write_json(job / "keyframes/gallery.json", items)
    return items
