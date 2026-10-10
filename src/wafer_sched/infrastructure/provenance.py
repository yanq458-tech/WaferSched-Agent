"""Verify both original identity and the explicit, sealed migration transform."""
import hashlib
import json
from .paths import PROJECT_ROOT


def assert_original_or_migrated(name, original_expected):
    actual = hashlib.sha256((PROJECT_ROOT / name).read_bytes()).hexdigest()
    if actual == original_expected:
        return
    if name.startswith("results/"):
        seal = json.loads((PROJECT_ROOT / "provenance/migration_manifest.json").read_text(encoding="utf-8"))
        row = seal["historical_assets"][name]
    else:
        rows = json.loads((PROJECT_ROOT / "provenance/source_migration.json").read_text(encoding="utf-8"))
        row = rows[name]
    assert row["original_sha256"] == original_expected, name
    assert row["release_sha256"] == actual, name
