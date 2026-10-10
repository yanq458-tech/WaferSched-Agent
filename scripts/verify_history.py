"""Verify historical release assets without accessing the original project."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from wafer_sched.infrastructure.paths import PROJECT_ROOT, resolve_path
from wafer_sched.infrastructure.io import atomic_record
from wafer_sched.metrics import calculate_metrics
from wafer_sched.config import load_config
from wafer_sched.agent.skills import replay_decisions


def verify(*, replay=True):
    seal = json.loads((PROJECT_ROOT / "provenance/migration_manifest.json").read_text(encoding="utf-8"))
    missing, changed = [], []
    for name, row in seal["historical_assets"].items():
        path = PROJECT_ROOT / name
        if not path.is_file():
            missing.append(name)
        elif hashlib.sha256(path.read_bytes()).hexdigest() != row["release_sha256"]:
            changed.append(name)
    if missing or changed:
        raise ValueError({"missing_assets": missing, "changed_assets": changed})
    counts, replays, incomplete = Counter(), 0, 0
    for path in sorted((PROJECT_ROOT / "results/wafer_sched").rglob("metrics.json")):
        directory = path.parent
        plain, compressed = directory / "events.json", directory / "events.json.gz"
        if not plain.exists() and not compressed.exists():
            continue
        raw = plain.read_bytes() if plain.exists() else gzip.decompress(compressed.read_bytes())
        events = json.loads(raw)["events"]
        saved = json.loads(path.read_text(encoding="utf-8"))
        if calculate_metrics(events) != saved:
            raise AssertionError("Historical metric mismatch: " + str(path.relative_to(PROJECT_ROOT)))
        counts[path.relative_to(PROJECT_ROOT / "results/wafer_sched").parts[0]] += 1
        decisions = directory / "decisions.json"
        if replay and decisions.exists():
            values = json.loads(decisions.read_text(encoding="utf-8"))
            rows = values["decisions"] if isinstance(values, dict) else values
            if saved["unfinished_wafers"]:
                incomplete += 1
                continue
            state = json.loads((directory / "state.json").read_text(encoding="utf-8"))
            sim = replay_decisions(load_config(directory / "config.json"), rows,
                                   saved["window_end_seconds"], state.get("seed", 0))
            if not sim.completed or calculate_metrics(sim.trace) != saved:
                raise AssertionError("Independent decision replay differs")
            replays += 1
    models = []
    import zipfile
    for path in sorted((PROJECT_ROOT / "results/wafer_sched/stage5").rglob("*.zip")):
        with zipfile.ZipFile(path) as archive:
            if archive.testzip() is not None:
                raise AssertionError("Model archive CRC differs")
        models.append({"path": path.relative_to(PROJECT_ROOT).as_posix(),
                       "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    original_models = json.loads((PROJECT_ROOT / "results/wafer_sched/stage5/verification.json").read_text(encoding="utf-8"))["model_sha256"]
    for name, expected in original_models.items():
        if hashlib.sha256((PROJECT_ROOT / "results/wafer_sched/stage5" / name).read_bytes()).hexdigest() != expected:
            raise AssertionError("Original formal model changed")
    return {"status": "passed", "historical_assets_verified": len(seal["historical_assets"]),
            "byte_identical_assets": seal["byte_identical_assets"],
            "explicitly_normalized_assets": seal["normalized_assets"],
            "metrics_recomputed": dict(counts), "metric_count": sum(counts.values()),
            "metric_mismatches": 0, "independent_completed_decision_replays": replays,
            "incomplete_cases_not_counted_as_passes": incomplete,
            "model_zip_crc_count": len(models), "formal_original_model_hash_matches": len(original_models),
            "models": models, "original_platform_required": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="results/release_validation/history.json")
    parser.add_argument("--no-replay", action="store_true")
    args = parser.parse_args()
    result = verify(replay=not args.no_replay)
    output = resolve_path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_record(output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
