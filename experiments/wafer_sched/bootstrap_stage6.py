"""Verify the bundled upstream source subset; never read an external vendor tree."""
import hashlib
import json
from wafer_sched.infrastructure.paths import PROJECT_ROOT


def main():
    root = PROJECT_ROOT / "src/wafer_sched/agent/_semantica"
    provenance = json.loads((root / "PROVENANCE.json").read_text(encoding="utf-8"))
    for name, expected in provenance["files"].items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
            raise ValueError("Bundled Semantica provenance differs")
    print("12 bundled upstream modules verified; no original platform is required")


if __name__ == "__main__":
    main()
