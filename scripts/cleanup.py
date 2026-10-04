import argparse

from app.config import Settings
from app.jobs import cleanup_jobs

parser = argparse.ArgumentParser(
    description="Cleanup terminal jobs older than configured retention"
)
parser.add_argument("--apply", action="store_true", help="Delete eligible jobs; default is dry run")
args = parser.parse_args()
settings = Settings.from_env()
if settings.retention_days <= 0:
    print("Cleanup disabled. Set LINKO_RETENTION_DAYS to a positive number to opt in.")
else:
    print(
        "Deleted" if args.apply else "Would delete", cleanup_jobs(settings, dry_run=not args.apply)
    )
