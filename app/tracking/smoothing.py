import copy
import math

from app.pose.schema import confidence


def alpha(cutoff, dt):
    return 1.0 / (1.0 + 1.0 / (2.0 * math.pi * cutoff * dt))


class OneEuro:
    def __init__(self, min_cutoff, beta, derivative_cutoff):
        self.min_cutoff, self.beta, self.derivative_cutoff = min_cutoff, beta, derivative_cutoff
        self.previous = self.filtered = self.derivative = None

    def apply(self, value, dt):
        if self.previous is None:
            self.previous = self.filtered = value
            self.derivative = 0.0
            return value
        speed = (value - self.previous) / dt
        a = alpha(self.derivative_cutoff, dt)
        self.derivative += a * (speed - self.derivative)
        cutoff = self.min_cutoff + self.beta * abs(self.derivative)
        self.filtered += alpha(cutoff, dt) * (value - self.filtered)
        self.previous = value
        return self.filtered


class PoseSmoother:
    """No interpolation or stale landmarks; multiple poses bypass filtering."""

    def __init__(self, settings):
        self.settings = settings
        self.filters = {}
        self.last_time = None
        self.last_positions = {}

    def apply(self, poses, timestamp):
        output = copy.deepcopy(poses)
        dt = timestamp - self.last_time if self.last_time is not None else 0
        if len(poses) != 1 or dt <= 0 or dt > self.settings.reset_gap_seconds:
            self.filters.clear()
            self.last_positions.clear()
        if len(poses) != 1:
            self.last_time = None
            return output
        for landmark in output[0]["landmarks"]:
            i = landmark["id"]
            position = (landmark["x"], landmark["y"])
            previous = self.last_positions.get(i)
            jumped = (
                previous
                and dt > 0
                and all(v is not None for v in (*position, *previous))
                and math.dist(position, previous) / dt > self.settings.jump_speed
            )
            unreliable = confidence(landmark) < self.settings.confidence_threshold
            for space, measurements in (("normalized", landmark), ("world", landmark["world"])):
                if measurements is None:
                    continue
                for axis in ("x", "y", "z"):
                    key = (i, space, axis)
                    value = measurements[axis]
                    if value is None or unreliable or jumped:
                        self.filters.pop(key, None)
                        continue
                    if key not in self.filters:
                        self.filters[key] = OneEuro(
                            self.settings.min_cutoff,
                            self.settings.beta,
                            self.settings.derivative_cutoff,
                        )
                    measurements[axis] = self.filters[key].apply(value, max(dt, 1e-6))
            self.last_positions[i] = position
        self.last_time = timestamp
        return output
