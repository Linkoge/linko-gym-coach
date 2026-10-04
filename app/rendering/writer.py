from fractions import Fraction

import av


class OverlayWriter:
    """H.264 MP4 with original presentation timing and browser-friendly faststart."""

    def __init__(self, path, metadata):
        self.container = av.open(
            str(path), mode="w", format="mp4", options={"movflags": "+faststart"}
        )
        self.stream = self.container.add_stream("libx264", rate=Fraction(metadata["fps_fraction"]))
        self.stream.width = metadata["width"]
        self.stream.height = metadata["height"]
        # yuv420p requires even dimensions; rare odd-size videos use yuv444p without cropping.
        self.stream.pix_fmt = (
            "yuv420p" if not (metadata["width"] % 2 or metadata["height"] % 2) else "yuv444p"
        )
        self.stream.time_base = Fraction(1, 1_000_000)
        self.stream.codec_context.time_base = Fraction(1, 1_000_000)
        self.stream.options = {"crf": "18", "preset": "medium", "bf": "0"}
        self.closed = False

    def write(self, rgb, timestamp):
        frame = av.VideoFrame.from_ndarray(rgb, format="rgb24")
        frame.pts = round(timestamp * 1_000_000)
        frame.time_base = Fraction(1, 1_000_000)
        for packet in self.stream.encode(frame):
            self.container.mux(packet)

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            for packet in self.stream.encode():
                self.container.mux(packet)
        finally:
            self.container.close()
