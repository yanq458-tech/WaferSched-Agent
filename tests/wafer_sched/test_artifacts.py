"""Real artifact publication and replay, isolated from the platform's live store."""

import csv
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys

import pytest

from wafer_sched import Action, EquipmentConfig, Simulator, load_config
from wafer_sched.artifacts import save_run
from wafer_sched.driver import run_validation_driver
from wafer_sched.metrics import calculate_metrics

ROOT = Path(__file__).resolve().parents[2]


def test_config_and_event_artifacts_are_replayable_and_metrics_match_real_logs(tmp_path):
    config = load_config(ROOT / "configs/wafer_sched/minimal_demo.json")
    simulator = Simulator(config, seed=17)
    outcome = run_validation_driver(simulator)
    directory = save_run(simulator, outcome, run_id="test-run", output_root=tmp_path)
    restored = load_config(directory / "config.json")
    assert restored == config
    events = json.loads((directory / "events.json").read_text(encoding="utf-8"))["events"]
    metrics = json.loads((directory / "metrics.json").read_text(encoding="utf-8"))
    assert calculate_metrics(events) == metrics
    assert metrics["makespan_seconds"] == 47 and metrics["completed_wafers"] == 3
    repeated = Simulator(restored, seed=17)
    run_validation_driver(repeated)
    assert repeated.trace == events
    with (directory / "events.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == len(events) == 91
    assert rows[-1]["event"] == "WaferCompleted" and rows[-1]["completed_count"] == "3"
    assert len((directory / "events.txt").read_text(encoding="utf-8").splitlines()) == 91
    metadata = json.loads((directory / "state.json").read_text(encoding="utf-8"))
    assert metadata["constraints_valid"] and metadata["seed"] == 17
    assert len(metadata["config_sha256"]) == 64
    assert all(len(value) == 64 for value in metadata["core_source_sha256"].values())
    assert not list(tmp_path.rglob(".state-*")) and not list(tmp_path.rglob(".wafer-*"))


def test_existing_run_is_never_overwritten_and_run_id_cannot_escape(tmp_path):
    config = load_config(ROOT / "configs/wafer_sched/minimal_demo.json")
    simulator = Simulator(config)
    outcome = run_validation_driver(simulator)
    directory = save_run(simulator, outcome, run_id="immutable", output_root=tmp_path)
    original = (directory / "events.json").read_bytes()
    with pytest.raises(FileExistsError):
        save_run(simulator, outcome, run_id="immutable", output_root=tmp_path)
    assert (directory / "events.json").read_bytes() == original
    with pytest.raises(ValueError):
        save_run(simulator, outcome, run_id="../escaped", output_root=tmp_path)


def test_route_alternatives_and_directional_travel_survive_json_roundtrip():
    original = load_config(ROOT / "configs/wafer_sched/minimal_demo.json")
    alternate = replace(original.chambers[1], processing_times=(("clean", 9), ("rinse", 6)))
    wafer = replace(original.wafers[0], route=(
        replace(original.wafers[0].route[0], chambers=("CLEAN", "RINSE")),))
    config = replace(original, chambers=(original.chambers[0], alternate), wafers=(wafer,),
                     robot=replace(original.robot, travel_times=(("LOAD", "RINSE", 2.5),)))
    assert EquipmentConfig.from_dict(json.loads(json.dumps(config.to_dict()))) == config
    simulator = Simulator(config)
    assert simulator.validate_action(Action.transfer("W1", "RINSE"))
    # Input: 1 + 2.5 + 1; process9; output1+1+1 => 16.5 seconds.
    assert simulator.submit(Action.transfer("W1", "RINSE"))
    run_validation_driver(simulator)
    assert calculate_metrics(simulator.trace)["makespan_seconds"] == 16.5


def test_completed_batch_refuses_new_actions_without_mutation():
    simulator = Simulator(load_config(ROOT / "configs/wafer_sched/minimal_demo.json"))
    run_validation_driver(simulator)
    before = simulator.snapshot()
    assert simulator.submit(Action.move("LOAD")).code == "batch_completed"
    assert simulator.submit(Action.wait()).code == "batch_completed"
    assert simulator.snapshot() == before


def test_demo_module_invocation_with_real_custom_config(tmp_path):
    config = load_config(ROOT / "configs/wafer_sched/minimal_demo.json")
    config_path = tmp_path / "single.json"
    config_path.write_text(json.dumps(replace(config, wafers=config.wafers[:1]).to_dict()),
                           encoding="utf-8")
    # Use an explicit isolated output root through the real publication entry point.
    simulator = Simulator(load_config(config_path))
    outcome = run_validation_driver(simulator)
    assert calculate_metrics(simulator.trace)["makespan_seconds"] == 19
    save_run(simulator, outcome, run_id="single", output_root=tmp_path / "results")
    # --help starts the actual module without publishing or touching live artifacts.
    command = subprocess.run([sys.executable, "-m", "wafer_sched.demo", "--help"],
                             cwd=ROOT, capture_output=True, text=True, timeout=10)
    assert command.returncode == 0 and "--print-events" in command.stdout


def test_failed_artifact_write_never_publishes_completed_summary(tmp_path, monkeypatch):
    from wafer_sched import artifacts

    simulator = Simulator(load_config(ROOT / "configs/wafer_sched/minimal_demo.json"))
    outcome = run_validation_driver(simulator)
    original = artifacts.atomic_record

    def fail_metrics(path, data):
        if path.name == "metrics.json":
            raise OSError("injected disk failure")
        original(path, data)

    monkeypatch.setattr(artifacts, "atomic_record", fail_metrics)
    with pytest.raises(OSError, match="disk failure"):
        save_run(simulator, outcome, run_id="interrupted", output_root=tmp_path)
    assert not (tmp_path / "interrupted/state.json").exists()
