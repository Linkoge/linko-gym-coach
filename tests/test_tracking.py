import copy
import math
import statistics

import pytest

from app.tracking.quality import QualityTracker
from app.tracking.smoothing import OneEuro, PoseSmoother
from app.tracking.storage import PoseWriter, read_records
from tests.conftest import pose, record


def test_filter_reduces_small_jitter_without_changing_input(settings):
    smoother = PoseSmoother(settings)
    raw_x, smooth_x = [], []
    for frame in range(180):
        x = 0.5 + 0.008 * (-1 if frame % 2 else 1)
        source = pose(x)
        before = copy.deepcopy(source)
        filtered = smoother.apply(source, frame / 60)
        assert source == before
        assert filtered[0]["landmarks"][0]["visibility"] == 0.95
        raw_x.append(x)
        smooth_x.append(filtered[0]["landmarks"][0]["x"])
    assert statistics.pstdev(smooth_x[20:]) < statistics.pstdev(raw_x) * 0.3


def test_adaptive_filter_tracks_fast_motion_more_quickly():
    adaptive, fixed = OneEuro(3, 0.4, 1), OneEuro(3, 0, 1)
    error_adaptive = error_fixed = 0
    for frame in range(120):
        value = 0.5 + 0.3 * math.sin(2 * math.pi * frame / 30)
        error_adaptive += abs(value - adaptive.apply(value, 1 / 60))
        error_fixed += abs(value - fixed.apply(value, 1 / 60))
    assert error_adaptive < error_fixed


def test_gap_low_confidence_jumps_and_multiple_people_reset(settings):
    smoother = PoseSmoother(settings)
    smoother.apply(pose(), 0)
    smoother.apply(pose(0.501), 1 / 30)
    assert smoother.apply([], 2 / 30) == []
    assert smoother.apply(pose(0.9), 3 / 30) == pose(0.9)
    low = pose(0.91, visibility=0.1)
    assert smoother.apply(low, 4 / 30) == low
    assert smoother.apply(pose(0.92), 5 / 30) == pose(0.92)
    multiple = pose(0.1) + pose(0.8)
    assert smoother.apply(multiple, 6 / 30) == multiple
    assert smoother.apply(pose(0.3), 7 / 30) == pose(0.3)
    assert smoother.apply(pose(0.4), 1.0) == pose(0.4)


def test_jsonl_round_trip_retains_confidence_missing_world_and_outside(tmp_path):
    source = record(0, pose(-0.2, visibility=0.01))
    source["poses"][0]["landmarks"][0]["world"] = None
    path = tmp_path / "raw.jsonl.gz"
    writer = PoseWriter(path)
    writer.write(source)
    writer.write(record(1, []))
    writer.close()
    assert list(read_records(path)) == [source, record(1, [])]


def assess(tmp_path, settings, rows):
    tracker = QualityTracker(tmp_path, settings)
    try:
        for row in rows:
            tracker.add(row)
        return tracker.finish(rows[-1]["timestamp_s"] + 1 / 30)
    finally:
        tracker.close()


def test_good_tracking_is_high(tmp_path, settings):
    result = assess(tmp_path, settings, [record(i, pose()) for i in range(30)])
    assert result["quality"] == "High"
    assert result["person_detected_percent"] == 100
    assert result["mean_landmark_visibility"] == pytest.approx(0.95)
    assert result["tracking_interruptions"] == 0


def test_no_person_still_produces_report(tmp_path, settings):
    result = assess(tmp_path, settings, [record(i, []) for i in range(30)])
    assert result["quality"] == "Low"
    assert result["frames_processed"] == 30
    assert result["tracking_interruptions"] == 1
    assert result["longest_interruption_seconds"] == 1
    assert all(item["lost_percent"] == 100 for item in result["landmark_loss"])


def test_quality_flags_gap_crop_occlusion_jumps_depth_and_ambiguity(tmp_path, settings):
    rows = [
        record(0, pose()),
        record(1, []),
        record(2, []),
        record(3, pose()),
        record(4, pose(0.9)),
        record(5, pose(0.9, visibility=0.1)),
        record(6, pose(-0.2)),
        record(7, pose(0.9) + pose(0.2)),
        record(8, pose(0.01)),
        record(9, pose(0.01)),
    ]
    rows[-1]["poses"][0]["landmarks"][25]["z"] = 1
    result = assess(tmp_path, settings, rows)
    assert result["tracking_interruptions"] == 1
    assert result["person_detected_percent"] == 80
    assert result["out_of_frame_frames"] == 1
    assert result["possible_occlusion_frames"] == 1
    assert result["multiple_person_frames"] == 1
    assert result["jump_frames"] >= 1
    assert result["depth_unstable_frames"] == 1
    assert result["near_edge_frames"] == 2
    assert result["quality"] != "High"
