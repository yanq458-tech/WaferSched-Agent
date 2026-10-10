"""Research artifacts reuse platform atomic publication without taking its lease."""

import csv
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

from wafer_sched.infrastructure.io import safe_run_id
from wafer_sched.infrastructure.io import durable_replace
from wafer_sched.infrastructure.io import new_run_id
from wafer_sched.infrastructure.io import atomic_record

from .metrics import calculate_metrics
from .simulator import Simulator

from .infrastructure.paths import PROJECT_ROOT


def _atomic_text(path: Path, text: str):
    descriptor, temporary = tempfile.mkstemp(prefix=".wafer-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        durable_replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _atomic_bytes(path: Path, payload: bytes):
    descriptor, temporary = tempfile.mkstemp(prefix=".wafer-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        durable_replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def event_text(row: dict) -> str:
    before, after = row["state_before"], row["state_after"]
    changes = []
    for name in ("position", "phase", "carrying"):
        left, right = before["robot"][name], after["robot"][name]
        if left != right:
            changes.append(f"robot.{name}:{left}->{right}")
    for key, wafer in after["wafers"].items():
        prior = before["wafers"][key]
        if (prior["location"], prior["stage"], prior["status"]) != (
                wafer["location"], wafer["stage"], wafer["status"]):
            changes.append(f"{key}:{prior['location']}/{prior['stage']}/{prior['status']}"
                           f"->{wafer['location']}/{wafer['stage']}/{wafer['status']}")
    for key, chamber in after["chambers"].items():
        prior = before["chambers"][key]
        if (prior["wafer_id"], prior["status"], prior["available"]) != (
                chamber["wafer_id"], chamber["status"], chamber["available"]):
            changes.append(f"{key}:{prior['wafer_id']}/{prior['status']}/{prior['available']}"
                           f"->{chamber['wafer_id']}/{chamber['status']}/{chamber['available']}")
    return (f"{row['index']:03d} t={row['time']:g} [{row['start_time']:g},{row['end_time']:g}] "
            f"{row['event']} wafer={row['wafer_id']} robot={row['robot_position']} "
            f"source={row['source']} destination={row['destination']} "
            f"target={row['target_chamber']} completed={row['completed_count']} "
            + "; ".join(changes)).rstrip()


def save_run(simulator: Simulator, outcome: dict, *, run_id: str | None = None,
             output_root: Path | None = None, compress_events: bool = False) -> Path:
    root = (output_root or PROJECT_ROOT / "results/wafer_sched").resolve()
    identifier = safe_run_id(run_id) if run_id else new_run_id()
    directory = root / identifier
    if not directory.resolve().is_relative_to(root):
        raise ValueError("Research artifacts escape their output root")
    directory.mkdir(parents=True, exist_ok=False)
    configuration = simulator.config.to_dict()
    core_hashes = {path.relative_to(Path(__file__).parent).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                   for path in sorted(Path(__file__).parent.rglob("*.py"))}
    metadata = {
        "run_id": identifier, "driver": "validation_only", "seed": simulator.seed,
        "python_version": sys.version.split()[0], **outcome,
        "constraints_valid": bool(simulator.validate_state()),
        "config_sha256": hashlib.sha256(json.dumps(configuration, sort_keys=True).encode()).hexdigest(),
        "core_source_sha256": core_hashes,
    }
    atomic_record(directory / "config.json", configuration)
    events = {"schema_version": 1, "events": simulator.trace}
    if compress_events:
        _atomic_bytes(directory / "events.json.gz", gzip.compress(
            json.dumps(events, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), mtime=0))
    else:
        atomic_record(directory / "events.json", events)
    atomic_record(directory / "metrics.json", calculate_metrics(simulator.trace))
    atomic_record(directory / "final_state.json", simulator.snapshot())
    import io

    stream = io.StringIO(newline="")
    fields = ["index", "time", "event", "start_time", "end_time", "interval_semantics",
              "wafer_id", "source", "destination", "target_chamber", "robot_position",
              "completed_count", "state_changes"]
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    for row in simulator.trace:
        writer.writerow({**{field: row[field] for field in fields if field != "state_changes"},
                         "state_changes": event_text(row)})
    _atomic_text(directory / "events.csv", stream.getvalue())
    _atomic_text(directory / "events.txt", "\n".join(map(event_text, simulator.trace)) + "\n")
    # Publish a completed summary only after every artifact has been durably written.
    atomic_record(directory / "state.json", metadata)
    return directory
