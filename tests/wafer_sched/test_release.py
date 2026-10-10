"""Independent migration boundary tests; no model training or old project reads."""
import ast
import hashlib
import json
from threading import Event

import pytest

from wafer_sched.infrastructure.io import atomic_record
from wafer_sched.infrastructure.paths import PROJECT_ROOT, relative_path, resolve_path
from wafer_sched.infrastructure.scheduler import WorkspaceRunScheduler


def test_no_runtime_platform_imports_and_unchanged_physical_core():
    for path in (PROJECT_ROOT / "src/wafer_sched").rglob("*.py"):
        if "_semantica" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("api.")
            elif isinstance(node, ast.Import):
                assert all(n.name != "api" and not n.name.startswith("api.") for n in node.names)
    before = json.loads((PROJECT_ROOT / "provenance/original_research_sha256.json").read_text(encoding="utf-8"))
    for name in ["simulator", "equipment", "events", "actions", "verification", "metrics",
                 "observation", "policy_runner", "cpsat_model", "cpsat_solver", "cpsat_validator",
                 "rl/environment", "rl/encoding", "rl/reward"]:
        key = f"src/wafer_sched/{name}.py"
        assert hashlib.sha256((PROJECT_ROOT / key).read_bytes()).hexdigest() == before[key]
    assert not (PROJECT_ROOT / "api").exists()


def test_atomic_failure_preserves_prior_record_and_relative_paths(tmp_path):
    path = tmp_path / "record.json"
    atomic_record(path, {"time": 3, "label": "??"})
    before = path.read_bytes()
    with pytest.raises(TypeError):
        atomic_record(path, {"invalid": object()})
    assert path.read_bytes() == before and not list(tmp_path.glob(".state-*"))
    config = PROJECT_ROOT / "configs/wafer_sched/minimal_demo.json"
    assert relative_path(config) == "configs/wafer_sched/minimal_demo.json"
    assert resolve_path(relative_path(config)) == config


def test_scheduler_capacity_exception_and_shutdown():
    release, started = Event(), Event()
    queue = WorkspaceRunScheduler(max_workers=1, max_pending_per_workspace=1, queue_timeout=2)
    try:
        def work():
            started.set()
            release.wait(2)
            return 42
        future = queue.submit("equipment", work)
        assert started.wait(1)
        with pytest.raises(RuntimeError, match="capacity"):
            queue.submit("equipment", lambda: 0)
        release.set()
        assert future.result(timeout=2) == 42
    finally:
        release.set()
        queue.shutdown()
    with pytest.raises(RuntimeError, match="closed"):
        queue.submit("equipment", lambda: 0)
