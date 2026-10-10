"""Launch only this repository's optional model worker."""
from pathlib import Path
import runpy
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
runpy.run_module("wafer_sched.infrastructure.model_http_worker", run_name="__main__")
