"""Verify migrated real history with the independent release verifier."""
import runpy
from wafer_sched.infrastructure.paths import PROJECT_ROOT


if __name__ == "__main__":
    runpy.run_path(str(PROJECT_ROOT / "scripts/verify_history.py"), run_name="__main__")
