# Stage 1: pose-tracking foundation

The question is whether single-camera workout videos provide credible body pose
for subsequent biomechanics. Running the estimator successfully is a software
check, not the acceptance decision. Stage 1 excludes recognition, rep counting,
angles, exercise scoring, reasoning, and coaching.

## Engine

MediaPipe 0.10.32, Pose Landmarker Heavy float16 v1, CPU, VIDEO running mode,
`num_poses=2`, detection/presence/tracking minimums all 0.5, segmentation off.
VIDEO mode uses temporal tracking; each frame is processed synchronously so no
busy-frame dropping occurs. Model SHA-256:
`64437af838a65d18e5ba7a0d39b465540069bc8aae8308de3e318aad31fcbc7b`.
The [official Python guide](https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker/python)
describes the mode, configuration, and normalized/world outputs; the
[model overview](https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker)
documents the Heavy bundle and 33-landmark vocabulary.

All returned poses/landmarks and confidences are stored before application
smoothing. Detector-level thresholds still mean the engine can return no pose;
unreturned landmarks cannot be recovered. World coordinates are learned
estimates in meters relative to the hip midpoint, not calibrated motion capture.
Pose indices are frame-local ordering, not identity tracking. The two-pose
configuration enables ambiguity reporting but can miss additional people.

## Machine-readable data

`raw.jsonl.gz` and `smoothed.jsonl.gz` are gzip-compressed JSON Lines, with one
JSON object for every decoded frame including no detections. Example:

```json
{"schema_version":1,"frame_number":0,"timestamp_s":0.0,"source_timestamp_s":0.0,"estimator_timestamp_ms":0,"poses":[{"pose_index":0,"landmarks":[{"id":23,"name":"left_hip","x":0.45,"y":0.55,"z":-0.01,"visibility":0.92,"presence":0.98,"world":{"x":-0.1,"y":0.0,"z":0.02,"visibility":0.92,"presence":0.98}}]}]}
```

Actual poses include every returned landmark; the abbreviated example shows
only one. `poses=[]` preserves a no-detection frame. Missing/unavailable/nonfinite
fields are `null`, not fabricated zeros. X/Y refer to the upright display image.
Normalized coordinates may leave [0,1] and are not clamped in stored data. World
landmark confidence values are stored separately from normalized confidence.
`schema.json` records coordinate definitions, engine checksum/settings, and
filter parameters. Stream it without decompressing into memory:

```python
from app.tracking.storage import read_records
for frame in read_records(path):
    print(frame["frame_number"], frame["timestamp_s"], len(frame["poses"]))
```

Per-frame quality metrics are in `metrics.sqlite3`, table `frames`, columns
`frame,timestamp,confidence,movement,anomaly,detected`. `events.jsonl.gz` retains
every flagged frame plus all tracking interruption intervals. `quality.json`
contains aggregated numerical measurements, thresholds, label, and limitations.

## Temporal smoothing

The application uses a causal [One Euro filter](https://gery.casiez.net/1euro/),
independently per landmark,
coordinate axis, and normalized/world coordinate space. For a frame interval
Δt and cutoff f, α = 1 / (1 + 1 / (2πfΔt)). The raw velocity is the change in
coordinate divided by Δt. Low-pass velocity at 1 Hz, then set the position
cutoff to `3 Hz + 0.4 × |filtered velocity|` and low-pass the coordinate at that
cutoff. These parameters are configurable and recorded per job.

This reduces slow jitter while permitting faster response to faster motion.
It can still cause lag; visual comparison is mandatory. Normalized and world
axes have different units, so the same beta is a pragmatic starting point,
not a biomechanically calibrated optimum. No confidence value is smoothed.

Reset/bypass policies:

- First frame and gaps longer than 0.2 s start new filter state.
- No pose returns no smoothed pose and clears state; no interpolation.
- A landmark with min(visibility,presence) < 0.5 passes through unchanged and
  its filters reset. Missing coordinates stay null.
- A raw normalized XY jump above 4 units/s passes through and resets that landmark.
- Frames with multiple poses pass through entirely and clear state to avoid
  filtering between frame-local pose identities.

Raw coordinates are never overwritten. MediaPipe's own internal processing is
part of the estimator output; “raw” means before this application's filter.
Both overlay MP4s and each gallery's three views expose the difference.

## Tracking-quality policy

Measurements use raw data:

| Measurement | Definition |
| --- | --- |
| Person detected | Frames with ≥1 returned pose / all decoded frames |
| Mean visibility / presence | Arithmetic mean of available returned values, with sample counts |
| Mean body confidence | Mean min(visibility,presence) for IDs 11–32 across returned poses |
| Landmark loss | No detection or min confidence <0.5; exclude ambiguous multi-pose frames from numerator/denominator |
| Interruptions | Consecutive runs with zero poses, including leading/trailing runs; record times/frame range |
| Jumps | Reliable single-pose XY displacement / Δt >4 normalized units/s |
| Depth instability | Reliable single-pose normalized Z displacement / Δt >4 units/s |
| Out of frame | Estimated body X/Y outside [0,1], including low-confidence estimates |
| Near edge | Body coordinates inside image but within 3% of an edge |
| Possible occlusion | Low-confidence body landmark inside the image, away from the edge |
| Multiple people | Frames with two returned poses; no persistent subject assignment |

Jumps/depth compare adjacent reliable single-pose frames only, never across
missing/multi-pose frames or gaps >0.2 s. Speeds are image-normalized heuristics;
they are not a physical plausibility test in calibrated space. Fast real motion
or camera motion can trigger them. Occlusion can also mean model failure; no
pixel-level occluder detector is implemented. Bounds/depth flags describe
estimates, not ground truth.

**Medium** requires detection ≥80%, mean body confidence ≥0.5, and jump frames
≤10%. **High** additionally requires detection ≥95%, mean body confidence ≥0.8,
jump frames ≤1%, longest interruption ≤0.5 s, zero multi-person frames, out-of-
frame frames ≤5%, and depth-instability frames ≤1%. Otherwise **Low**. Labels
never block completed outputs. All numerical measurements remain available.
Means over returned values do not count missing frames as confident detections;
the detection percentage reports that separately. A High result can be wrong.

## Verification gallery

Select six evenly distributed anchors (early, 20%, 40%, 60%, 80%, late), then
add the highest confidence detected frame, lowest overall confidence frame,
greatest observed XY movement frame, and worst-confidence anomaly frame.
Deduplicate indices: ≤10 frames; very short/static clips may have fewer distinct
extremes. Each has an original, raw overlay, smoothed overlay, source frame
number, actual timestamp, mean confidence, and selection reasons. Full-size
JPEGs are linked from the page. This is tracking verification only.

## Manual validation

1. Run setup/tests and the local server. Use consenting local footage, or
   `uv run python -m scripts.validation_samples` for openly licensed demos.
   Keep private sources and screenshots under `data/`, never `docs/`.
2. Upload through the browser. Confirm filename/progress, stage updates,
   persistent job URL, automatic results display, and successful file downloads.
3. Cover **native** 30 and 60 FPS, portrait and landscape, MP4 and practical MOV
   codecs, short clips, and a ~10-minute recording. Verify ffprobe dimensions,
   rotation, duration, decoded/raw/overlay frame counts, timing, and browser playback.
   Duplicating frames to 60 FPS tests transport but not native high-speed motion.
4. Cover full body, cropped limbs, temporary occlusion, fast movement, frame
   edges, poor lighting, and multiple people where footage is available. Inspect
   quality numbers/events against actual visible tracking loss. Low quality must
   still produce files/gallery and explain limitations.
5. Play **both complete overlays**, first at normal speed, then 0.25×. Compare
   the original at the same timestamp. Scrub every repetition top/bottom and
   transitions, and all anomaly timestamps. Check hips, knees, ankles,
   shoulders, elbows, wrists; left/right identity; body-part jumps; apparent
   confidence during occlusions; smoothing lag and distortion.
6. Open all gallery comparisons at full resolution. Sample additional frames
   between gallery images; gallery coverage is not whole-video acceptance.
   Mark each landmark group Pass / Questionable / Fail with timestamps and reasons.
7. Exercise corrupt/unsupported/empty inputs and disconnect/restart the server.
   Verify safe user messages, preserved local inputs/logs, unavailable partial
   outputs, and no stack trace in the browser. Test FFmpeg absence and disk
   reserve errors in an isolated test data directory. Do not fill the machine's disk.
8. Confirm no external requests during processing (browser Network panel and
   local process monitoring), Git exclusions, and cleanup disabled. Opt-in
   cleanup testing uses a disposable data directory, never real validation jobs.
9. Record model hash, machine, versions, job IDs, scenario matrix, timing,
   screenshot provenance, problems, and remaining gaps in a validation report.

**Acceptance:** a reviewer must judge tracking visually credible on several
actual workout recordings and resolve questionable landmarks/lag before Stage 1
is marked successful. A numeric High label, screenshots alone, or model execution
without errors is insufficient. Stop at Stage 1 for review.
