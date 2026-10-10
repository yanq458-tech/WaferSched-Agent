"""Launch only this repository's fixed numerical worker."""
from pathlib import Path
import runpy
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
runpy.run_module("wafer_sched.agent.worker", run_name="__main__")
