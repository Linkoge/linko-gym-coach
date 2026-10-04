import gzip
import json


class PoseWriter:
    """One JSON object per frame, streamed and gzip compressed."""

    def __init__(self, path):
        self.file = gzip.open(path, "wt", encoding="utf-8", compresslevel=3)

    def write(self, record):
        self.file.write(json.dumps(record, separators=(",", ":"), allow_nan=False) + "\n")

    def close(self):
        self.file.close()


def read_records(path):
    with gzip.open(path, "rt", encoding="utf-8") as file:
        for line in file:
            yield json.loads(line)
