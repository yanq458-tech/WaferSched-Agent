"""Repository-relative resources and portable persisted path identities."""
import os
from pathlib import Path

PROJECT_ROOT = Path(os.environ.get("WAFER_SCHED_ROOT", Path(__file__).resolve().parents[3])).resolve()


def resolve_path(value):
    path = Path(value)
    return (path if path.is_absolute() else PROJECT_ROOT / path).resolve()


def relative_path(value):
    return Path(os.path.relpath(resolve_path(value), PROJECT_ROOT)).as_posix()
