# Stage 1 validation report

Date: 2026-10-04. Local Linux CPU run, Python 3.12.15, MediaPipe 0.10.32,
PyAV 16.1.0, Heavy float16 v1; exact configuration/checksum is recorded in
every job's `tracking/schema.json`. Stage 1 implementation is ready for review;
**biomechanical suitability is not yet accepted**. No Stage 2 functionality was
implemented.

## Automated verification

23 tests passed, including actual MediaPipe inference. Ruff lint and formatting
checks pass. One upstream Starlette warning reports deprecated use of httpx in
TestClient; it does not affect application processing or the passing checks.
GitHub Actions configuration is added but has not run remotely.

Tests cover immutable raw pose preservation, gzip data round trips,
confidence/null/out-of-bounds storage, jitter reduction, velocity adaptation,
gap/low-confidence/multi-person filter resets, numerical quality calculations,
no-person completion, gaps/occlusion/edges/cropping/jumps/depth/ambiguity flags,
MP4/MOV output generation, 30/60 FPS, portrait/landscape, phone rotation,
variable presentation timestamps, preserved input bytes, overlay frame counts,
corrupt/unsupported/empty/oversized input, disk reserve, path allowlisting,
cross-origin uploads/invalid hosts, byte ranges, cleanup opt-in/active-job
protection, restart recovery, native worker exits, and stalled workers.

The fake pose adapter isolates pipeline mechanics from model correctness.
The real-model no-person test proves low-quality results are still generated;
it does not establish body tracking accuracy.

## Full long-recording run

A 600-second, 60 FPS, 160×120 synthetic black MP4 was processed with the actual
Heavy model, not a mocked adapter. Results:

- 36,000 decoded/tracked frames; 36,000 records in each raw/smoothed file.
- Both H.264 overlays: 36,000 frames, 600.0 seconds, 60 FPS.
- Six gallery entries, all generated successfully.
- Low tracking quality, 0% detection, one 600-second no-detection interval;
  processing was not rejected.
- 667.93 seconds processing wall time (~11m08s).
- Worker resident memory observed around 304 MiB during tracking at 28,732
  frames, without storing video frames/pose arrays in memory.

This verifies long-duration storage, timestamps, progress, and rendering with
real inference. It does not replace a native-resolution, ten-minute workout
validation with a person moving; resolution/model detections affect time/memory.

## Public workout demonstrations

Three real exercise demonstrations were downloaded explicitly to ignored
`data/validation-sources/`, converted to supported upload containers, and
processed through the local upload API. All frames produced raw/smoothed
records, two overlays, a gallery, and a report.

| Source | Upload variation | Frames | Detected | Mean body confidence | Quality |
| --- | --- | ---: | ---: | ---: | --- |
| FitnessScape weighted squat | 1280×720 MP4, 30 FPS | 213 | 100.0% | 0.846 | Medium |
| FitnessScape pull-ups | 1280×720 MP4, converted 60 FPS | 360 | 99.44% | 0.755 | Medium |
| RickyBennison single-leg squat | 480×640 MOV, 30 FPS | 235 | 100.0% | 0.803 | Medium |

The 60 FPS source is duplicated-frame conversion: it verifies frame transport,
not native 60 FPS motion capture. Sources/attribution:
[weighted squat](https://commons.wikimedia.org/wiki/File:Squat_-_exercise_demonstration_video.webm),
[pull-ups](https://commons.wikimedia.org/wiki/File:Pull-ups_-_exercise_demonstration_video.webm)
by FitnessScape ([CC BY 3.0](https://creativecommons.org/licenses/by/3.0/));
[single-leg squat](https://commons.wikimedia.org/wiki/File:Basic_single_leg_squat.webm)
by RickyBennison ([CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)).
Conversion and pose annotations are derivative changes; no endorsement implied.

Inspection evidence: 24 distributed raw-overlay frames per source and 12
raw/smoothed squat comparison frames, including the bottom and rising phases,
were inspected. Public comparison sheets remain under `data/public-review/`.
Browser playback was verified for original, raw, and smoothed MP4s. This is
**sampled visual inspection**, not a claim of continuous human review of every
frame in every overlay.

Observed limitations:

- Squat hips/upper torso/near-side limbs broadly follow the visible athlete in
  sampled frames. Far-side knees/hips overlap, hands contact a bar, and ankles
  are largely cropped. Anatomical location at occluded joints remains uncertain.
- Pull-up shoulders/elbows/wrists broadly follow the sampled arm motion.
  Lower legs are cropped, some knees lose confidence, a transition briefly
  has no detection, and depth/jump flags require review.
- Single-leg subject is small in frame. Tracking persists, but overlapping
  legs/hands and confidence loss prevent confidently accepting fine joint placement.
- Smoothed squat samples show small delays on rising/lowering frames. No severe
  body-part displacement was obvious in the sampled comparisons; fast motion
  and continuous playback still need human confirmation.
- Depth instability is flagged in 29/213 squat and 75/360 pull-up frames.
  Single-camera Z/world coordinates should not yet be treated as calibrated depth.
- One squat frame returns two poses although the source mainly depicts one
  subject; false-positive ambiguity is possible. The application preserves it,
  reports it, and bypasses smoothing rather than silently selecting a subject.

## Controlled stress variations

Public squat transformations (no claim of new real-world recordings):

| Transformation | Detection | Body confidence | Relevant result |
| --- | ---: | ---: | --- |
| Cropped to 800×480 | 99.06% | 0.565 | 2 gaps; substantial confidence reduction |
| Darkened | 99.06% | 0.846 | 1 gap; 17 jump flags; confidence alone misses some degradation |
| Edge crop | 100% | 0.831 | Out-of-frame flags on all 213 frames |
| Twice-speed, 60 FPS | 100% | 0.848 | 100 depth-instability frames; 2 ambiguity frames |
| Black occlusion 2–2.8s | 88.26% | 0.849 | 1 detection interruption; confidence mean remains high when present |

All five completed with Medium quality and accessible artifacts. These checks
show why detection coverage, events, and confidence must be assessed together.
A returned confidence mean alone does not identify every problem. Real poor
lighting, partial occlusion, multi-person recordings, and native high-speed
movement still need a broader footage set.

## Browser and privacy checks

Chromium automation exercised actual file selection/upload/redirect/processing
through the web interface, report rendering, all three playback modes,
gallery links/images, and a 390×844 mobile viewport. No JavaScript errors or
horizontal mobile overflow were observed. The repeatable `browser_smoke` script
asserts all page requests stay local and writes screenshots to ignored data.
The browser never calls an AI service. Video probing/decoding allow local
file/pipe protocols only. Model download is an explicit setup step.

Repository screenshots show only the licensed squat demonstration, with
[provenance](screenshots/README.md). User inputs, model bundles, full pose data,
diagnostics, and test jobs are Git-ignored. Cleanup dry-run reports disabled;
no development or user job was deleted.

## Acceptance still requiring review

Both supplied local workout clips completed processing and output checks;
original bytes, raw/smoothed/overlay frame counts, dimensions, duration,
gallery files, and browser playback all passed. Their private job
reports, screenshots, and overlays stay under ignored `data/`. Human review
must check complete raw/smoothed videos, especially hips/knees/ankles, shoulders/
elbows/wrists, repetition extremes, occlusion, identity switches, and lag.
Record that verdict locally without copying private frames into this document.
Numerical reports and job URLs are saved in `data/local-validation-report.json`;
private browser screenshots are in `data/browser-review/<job-id>/`.

Additional outstanding checks: native 60 FPS moving workout footage, a
ten-minute workout with a person at ordinary phone resolution, broader cameras/
lighting/partial occlusion/multiple people, and physical browser/phone playback
(Chromium automation is not an iPhone/Safari acceptance test). Quality labels
are heuristics, not ground-truth anatomical validation.

Questionable design choices to review: no persistent subject identities; one
worker and three decode passes; two output videos double encoding/storage;
the same initial smoothing beta for normalized/world units; confidence-based
reset discontinuities; and arbitrary uncalibrated anomaly/quality thresholds.
These choices are documented and modular, but need benchmark evidence before
later biomechanics.

No Stage 2 is authorized or implemented. Review the foundation and visually
accept the tracking before declaring Stage 1 successful.
