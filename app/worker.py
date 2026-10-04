import argparse
import ctypes
import logging
import os
import signal
import sys

from app.config import Settings
from app.errors import ProcessingError
from app.jobs import job_path, update_job
from app.pipeline import process_job


def main():
    # Linux workers must not survive a hard server crash and race a restarted server.
    parent_pid = os.environ.get("LINKO_PARENT_PID")
    if sys.platform == "linux" and parent_pid:
        if ctypes.CDLL(None).prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
            raise RuntimeError("Unable to configure worker parent-death signal")
        if os.getppid() != int(parent_pid):
            return 1
    parser = argparse.ArgumentParser()
    parser.add_argument("job_id")
    args = parser.parse_args()
    settings = Settings.from_env()
    job = job_path(settings, args.job_id)
    logging.basicConfig(
        filename=job / "diagnostic.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        process_job(job, settings)
    except Exception as exc:
        logging.exception("Job processing failed")
        if isinstance(exc, ProcessingError):
            message = str(exc)
        elif isinstance(exc, OSError) and exc.errno == 28:
            message = "Disk space ran out. Free disk space and upload the video again."
        else:
            message = (
                "Processing failed. Check the local diagnostic log, then upload the video again."
            )
        update_job(job, state="failed", stage="Failed", error=message)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
