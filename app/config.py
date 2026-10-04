import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    allowed_hosts: str = "127.0.0.1,localhost,testserver"
    data_dir: Path = ROOT / "data"
    model_path: Path = ROOT / "models/pose_landmarker_heavy.task"
    max_upload_bytes: int = 4 * 1024**3
    min_free_bytes: int = 512 * 1024**2
    retention_days: float = 0  # Disabled; explicitly opt in.
    worker_stall_seconds: float = 300
    min_cutoff: float = 3.0
    beta: float = 0.4
    derivative_cutoff: float = 1.0
    reset_gap_seconds: float = 0.2
    confidence_threshold: float = 0.5
    jump_speed: float = 4.0  # normalized image widths/heights per second
    depth_speed: float = 4.0  # normalized image-width units per second

    @classmethod
    def from_env(cls):
        values = {}
        for name, field in cls.__dataclass_fields__.items():
            value = os.environ.get("LINKO_" + name.upper())
            if value is not None:
                default = field.default
                values[name] = type(default)(value)
        result = cls(**values)
        if any(isinstance(v, float) and not math.isfinite(v) for v in asdict(result).values()):
            raise ValueError("Numeric settings must be finite")
        if result.min_cutoff <= 0 or result.derivative_cutoff <= 0 or result.beta < 0:
            raise ValueError("Smoothing cutoffs must be positive and beta nonnegative")
        if result.reset_gap_seconds <= 0 or result.worker_stall_seconds <= 0:
            raise ValueError("Time limits must be positive")
        if not 0 <= result.confidence_threshold <= 1:
            raise ValueError("Confidence threshold must be between zero and one")
        if result.retention_days < 0 or result.max_upload_bytes <= 0:
            raise ValueError("Invalid retention or upload limit")
        if result.min_free_bytes < 0 or result.jump_speed <= 0 or result.depth_speed <= 0:
            raise ValueError("Disk reserve must be nonnegative and jump thresholds positive")
        return result

    def serializable(self):
        return {k: str(v) if isinstance(v, Path) else v for k, v in asdict(self).items()}
