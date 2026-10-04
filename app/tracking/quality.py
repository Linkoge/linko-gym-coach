import math
import sqlite3

from app.pose.schema import NAMES, confidence
from app.tracking.storage import PoseWriter

BODY = set(range(11, 33))


class QualityTracker:
    """Raw-data heuristics; anomaly events stay on disk, not in an unbounded list."""

    def __init__(self, directory, settings):
        self.settings = settings
        self.db = sqlite3.connect(directory / "metrics.sqlite3")
        self.db.execute(
            "CREATE TABLE frames (frame INTEGER PRIMARY KEY, timestamp REAL, "
            "confidence REAL, movement REAL, anomaly INTEGER, detected INTEGER)"
        )
        self.events = PoseWriter(directory / "events.jsonl.gz")
        self.total = self.detected = self.multi = self.interruptions = 0
        self.visibility_sum = self.visibility_n = self.presence_sum = self.presence_n = 0
        self.body_sum = self.body_n = 0
        self.lost = [0] * 33
        self.counts = {
            "jump_frames": 0,
            "depth_unstable_frames": 0,
            "out_of_frame_frames": 0,
            "near_edge_frames": 0,
            "possible_occlusion_frames": 0,
        }
        self.previous = None
        self.gap = None
        self.gap_first_frame = None
        self.longest_gap = 0
        self.interval_sample = []
        self.last_timestamp = 0

    def add(self, record):
        frame, timestamp, poses = record["frame_number"], record["timestamp_s"], record["poses"]
        self.total += 1
        self.last_timestamp = timestamp
        detected = bool(poses)
        self.detected += detected
        self.multi += len(poses) > 1
        if not detected:
            if self.gap is None:
                self.gap, self.gap_first_frame = timestamp, frame
            self.lost = [v + 1 for v in self.lost]
        elif self.gap is not None:
            self.end_gap(timestamp, frame - 1)
        confidences, body = [], []
        low, outside, edge = [], [], []
        for pose in poses:
            for lm in pose["landmarks"]:
                for key in ("visibility", "presence"):
                    if lm[key] is not None:
                        setattr(self, key + "_sum", getattr(self, key + "_sum") + lm[key])
                        setattr(self, key + "_n", getattr(self, key + "_n") + 1)
                c = confidence(lm)
                confidences.append(c)
                if lm["id"] in BODY:
                    body.append(c)
        # Per-landmark loss is evaluated on single-person frames only; ambiguity is reported.
        if len(poses) == 1:
            for lm in poses[0]["landmarks"]:
                i, x, y = lm["id"], lm["x"], lm["y"]
                unreliable = confidence(lm) < self.settings.confidence_threshold
                self.lost[i] += unreliable
                if i not in BODY or x is None or y is None:
                    continue
                if not (0 <= x <= 1 and 0 <= y <= 1):
                    outside.append(i)
                elif x < 0.03 or x > 0.97 or y < 0.03 or y > 0.97:
                    edge.append(i)
                elif unreliable:
                    low.append(i)
        self.body_sum += sum(body)
        self.body_n += len(body)
        mean = sum(confidences) / len(confidences) if confidences else 0.0
        jumps, depths, speeds = [], [], []
        if len(poses) == 1 and self.previous:
            old_time, old_landmarks = self.previous
            dt = timestamp - old_time
            if 0 < dt <= self.settings.reset_gap_seconds:
                for lm, old in zip(poses[0]["landmarks"], old_landmarks, strict=True):
                    if min(confidence(lm), confidence(old)) < self.settings.confidence_threshold:
                        continue
                    if all(v is not None for v in (lm["x"], lm["y"], old["x"], old["y"])):
                        speed = math.hypot(lm["x"] - old["x"], lm["y"] - old["y"]) / dt
                        speeds.append(speed)
                        if speed > self.settings.jump_speed:
                            jumps.append(lm["id"])
                    if lm["z"] is not None and old["z"] is not None:
                        if abs(lm["z"] - old["z"]) / dt > self.settings.depth_speed:
                            depths.append(lm["id"])
        self.previous = (timestamp, poses[0]["landmarks"]) if len(poses) == 1 else None
        flags = {
            "jump_frames": jumps,
            "depth_unstable_frames": depths,
            "out_of_frame_frames": outside,
            "near_edge_frames": edge,
            "possible_occlusion_frames": low,
        }
        for key, values in flags.items():
            self.counts[key] += bool(values)
        anomaly = any(flags.values()) or not detected or len(poses) > 1
        if anomaly:
            self.events.write(
                {"frame_number": frame, "timestamp_s": timestamp, "pose_count": len(poses), **flags}
            )
        movement = sum(speeds) / len(speeds) if speeds else 0.0
        self.db.execute(
            "INSERT INTO frames VALUES (?, ?, ?, ?, ?, ?)",
            (frame, timestamp, mean, movement, int(anomaly), int(detected)),
        )
        if self.total % 100 == 0:
            self.db.commit()
        return mean

    def end_gap(self, end, last_frame):
        self.interruptions += 1
        interval = {
            "start_s": self.gap,
            "end_s": end,
            "duration_s": end - self.gap,
            "first_frame": self.gap_first_frame,
            "last_frame": last_frame,
        }
        self.longest_gap = max(self.longest_gap, interval["duration_s"])
        if len(self.interval_sample) < 100:
            self.interval_sample.append(interval)
        self.events.write({"type": "tracking_interruption", **interval})
        self.gap = None

    def finish(self, end_timestamp):
        if self.gap is not None:
            self.end_gap(end_timestamp, self.total - 1)
        self.db.commit()
        self.events.close()
        detected_pct = 100 * self.detected / max(self.total, 1)
        body_mean = self.body_sum / max(self.body_n, 1)
        jump_rate = self.counts["jump_frames"] / max(self.total, 1)
        label = "Low"
        if detected_pct >= 80 and body_mean >= 0.5 and jump_rate <= 0.1:
            label = "Medium"
        if (
            detected_pct >= 95
            and body_mean >= 0.8
            and jump_rate <= 0.01
            and self.longest_gap <= 0.5
            and not self.multi
            and self.counts["out_of_frame_frames"] / max(self.total, 1) <= 0.05
            and self.counts["depth_unstable_frames"] / max(self.total, 1) <= 0.01
        ):
            label = "High"
        limitations = []
        if not self.detected:
            limitations.append("No person was detected. Outputs remain available for inspection.")
        if self.multi:
            limitations.append(
                "Multiple poses detected; subject identity is ambiguous. "
                "Smoothing is bypassed on these frames."
            )
        if self.counts["out_of_frame_frames"]:
            limitations.append("Some estimated body landmarks leave the image boundaries.")
        if self.counts["possible_occlusion_frames"]:
            limitations.append(
                "Low visibility inside the frame may indicate occlusion or model error."
            )
        if self.interruptions:
            limitations.append("Detection gaps occur; missing poses are not interpolated.")
        if self.counts["jump_frames"] or self.counts["depth_unstable_frames"]:
            limitations.append(
                "Sudden coordinate changes require visual verification; "
                "fast real motion can also trigger these heuristics."
            )
        return {
            "schema_version": 1,
            "quality": label,
            "frames_processed": self.total,
            "frames_with_person": self.detected,
            "person_detected_percent": detected_pct,
            "mean_landmark_visibility": self.visibility_sum / max(self.visibility_n, 1),
            "mean_landmark_presence": self.presence_sum / max(self.presence_n, 1),
            "mean_body_confidence": body_mean,
            "visibility_measurements": self.visibility_n,
            "presence_measurements": self.presence_n,
            "multiple_person_frames": self.multi,
            "tracking_interruptions": self.interruptions,
            "longest_interruption_seconds": self.longest_gap,
            "interruption_sample": self.interval_sample,
            "landmark_loss": [
                {
                    "id": i,
                    "name": name,
                    "lost_frames": self.lost[i],
                    "lost_percent": 100 * self.lost[i] / max(self.total - self.multi, 1),
                }
                for i, name in enumerate(NAMES)
            ],
            **self.counts,
            "limitations": limitations,
            "thresholds": {
                "confidence": self.settings.confidence_threshold,
                "jump_speed_normalized_units_per_s": self.settings.jump_speed,
                "depth_speed_normalized_units_per_s": self.settings.depth_speed,
            },
            "assessment_policy": "See docs/stage-1-pose-tracking.md. Heuristic tracking quality, "
            "not exercise quality or accuracy proof.",
        }

    def close(self):
        self.events.close()
        self.db.close()
