import cv2

from app.pose.schema import CONNECTIONS, confidence


def draw_overlay(rgb, poses, frame_number, timestamp, mean_confidence, mode="raw", threshold=0.5):
    image = rgb.copy()
    height, width = image.shape[:2]
    thickness = max(1, round(min(width, height) / 400))
    for pose in poses:
        landmarks = {lm["id"]: lm for lm in pose["landmarks"]}

        def point(lm):
            if lm["x"] is None or lm["y"] is None:
                return None
            # Outside-image landmarks stay in data, but never cause huge drawing coordinates.
            if not (-1 <= lm["x"] <= 2 and -1 <= lm["y"] <= 2):
                return None
            return round(lm["x"] * (width - 1)), round(lm["y"] * (height - 1))

        for a, b in CONNECTIONS:
            if a not in landmarks or b not in landmarks:
                continue
            pa, pb = point(landmarks[a]), point(landmarks[b])
            if pa is None or pb is None:
                continue
            reliable = min(confidence(landmarks[a]), confidence(landmarks[b])) >= threshold
            color = (45, 225, 175) if reliable else (255, 170, 60)
            cv2.line(image, pa, pb, color, thickness, cv2.LINE_AA)
        for lm in landmarks.values():
            p = point(lm)
            if p is None:
                continue
            reliable = confidence(lm) >= threshold
            cv2.circle(
                image,
                p,
                thickness * 2 + 1,
                (45, 225, 175) if reliable else (255, 170, 60),
                -1 if reliable else thickness,
                cv2.LINE_AA,
            )
    text = (
        f"{mode.upper()} | Frame {frame_number} | {timestamp:.2f}s | "
        f"Conf {mean_confidence:.2f} | Poses {len(poses)}"
    )
    scale = min(0.7, max(0.22, width / 1100))
    cv2.rectangle(image, (0, 0), (width, max(26, int(scale * 55))), (20, 28, 40), -1)
    cv2.putText(
        image,
        text,
        (6, max(18, int(scale * 36))),
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        (240, 245, 250),
        1,
        cv2.LINE_AA,
    )
    return image
