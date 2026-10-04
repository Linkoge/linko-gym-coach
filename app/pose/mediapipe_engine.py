import hashlib
import math
from importlib.metadata import version

from app.errors import ProcessingError
from app.pose.schema import NAMES


def finite(value):
    return float(value) if value is not None and math.isfinite(value) else None


class MediaPipeEngine:
    """All returned poses are preserved; result order is NOT an identity."""

    def __init__(self, settings):
        import mediapipe as mp

        if not settings.model_path.is_file():
            raise ProcessingError("Pose model is missing. Run scripts/download_model.py first.")
        self.mp = mp
        self.options = {
            "running_mode": "VIDEO",
            "num_poses": 2,
            "min_pose_detection_confidence": 0.5,
            "min_pose_presence_confidence": 0.5,
            "min_tracking_confidence": 0.5,
            "output_segmentation_masks": False,
            "delegate": "CPU",
        }
        options = mp.tasks.vision.PoseLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(
                model_asset_path=str(settings.model_path),
                delegate=mp.tasks.BaseOptions.Delegate.CPU,
            ),
            running_mode=mp.tasks.vision.RunningMode.VIDEO,
            num_poses=2,
            min_pose_detection_confidence=0.5,
            min_pose_presence_confidence=0.5,
            min_tracking_confidence=0.5,
            output_segmentation_masks=False,
        )
        self.task = mp.tasks.vision.PoseLandmarker.create_from_options(options)
        self.metadata = {
            "engine": "MediaPipe Pose Landmarker",
            "version": version("mediapipe"),
            "model": "pose_landmarker_heavy float16 v1",
            "model_sha256": hashlib.sha256(settings.model_path.read_bytes()).hexdigest(),
            "configuration": self.options,
        }

    def detect(self, rgb, timestamp_ms):
        image = self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb)
        result = self.task.detect_for_video(image, timestamp_ms)
        poses = []
        for index, normalized in enumerate(result.pose_landmarks):
            world = result.pose_world_landmarks[index] if result.pose_world_landmarks else []
            landmarks = []
            for i, landmark in enumerate(normalized):
                item = {"id": i, "name": NAMES[i]}
                item.update(
                    {
                        k: finite(getattr(landmark, k, None))
                        for k in ("x", "y", "z", "visibility", "presence")
                    }
                )
                item["world"] = (
                    {
                        k: finite(getattr(world[i], k, None))
                        for k in ("x", "y", "z", "visibility", "presence")
                    }
                    if i < len(world)
                    else None
                )
                landmarks.append(item)
            poses.append({"pose_index": index, "landmarks": landmarks})
        return poses

    def close(self):
        self.task.close()
