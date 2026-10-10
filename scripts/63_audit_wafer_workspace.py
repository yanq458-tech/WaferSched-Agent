"""Read-only first-party source audit; no project imports or equipment experiments.

Run with any Python >= 3.11. The JSON output describes static evidence, not
runtime acceptance of the existing agent or its optional dependencies.
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter
from datetime import datetime
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = Path("docs/workspace_inventory.json")
EXCLUDED_DIRECTORIES = frozenset({
    ".git", ".venv", ".venv_optimization", ".venv_wafer", "venv", "env",
    "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "dist", "build", "storage", "outputs", "results", ".vscode", ".idea",
    ".agents", ".codex", ".aws", ".ci", ".pytest-tmp", ".pytest-tmp2",
    ".workbuddy", ".playwright-cli",
})
DEPENDENCIES = {
    "semantica": "semantica", "ortools": "ortools", "pytest": "pytest",
    "ruff": "ruff", "gymnasium": "gymnasium",
    "stable_baselines3": "stable-baselines3", "sb3_contrib": "sb3-contrib",
    "torch": "torch", "matplotlib": "matplotlib", "reportlab": "reportlab",
    "langgraph": "langgraph",
}
CAPABILITY_EVIDENCE = {
    "domain_registration": ("api/domains/registry.py", "DomainRegistry"),
    "read_only_assistant": ("api/services/assistant.py", "AssistantService"),
    "optional_llm_rendering": ("api/services/assistant_llm.py", "AssistantLlm"),
    "structured_query_planner": (
        "api/services/assistant_graph_planner.py", "AssistantGraphPlanner"),
    "model_http_transport": ("api/services/model_transport.py", "model_completion"),
    "railway_cp_sat": ("api/services/railway_solver.py", "solve"),
    "run_journal": ("api/services/run_journal.py", "RunJournal"),
    "run_scheduler": ("api/services/run_scheduler.py", "WorkspaceRunScheduler"),
    "read_only_agent_preview": (
        "api/services/report_analysis_service.py", "build_agent_preview"),
}


def excluded_file(path: Path) -> bool:
    """Do not read credentials, runtime databases, lock files, or generated audit."""
    name = path.name.lower()
    return (
        name == ".env" or name.startswith(".env.")
        or name.endswith((".key", ".pem", ".p12", ".pfx", ".log", ".tmp", ".lock"))
        or name.endswith((".sqlite", ".sqlite3", ".db", ".pyc", ".pyd"))
        or name.startswith(("credentials", "secrets"))
        or name == "workspaces.local.json"
        or path.as_posix() == DEFAULT_OUTPUT.as_posix()
    )


def source_details(source: bytes, relative: str) -> dict:
    """Parse source as data: a scanned module is never imported or executed."""
    text = source.decode("utf-8-sig")
    tree = ast.parse(text, filename=relative)
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add("." * node.level + (node.module or ""))
    return {
        "lines": len(text.splitlines()),
        "imports": sorted(imports),
        "definitions": [
            {"name": node.name, "kind": type(node).__name__, "line": node.lineno}
            for node in tree.body
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        ],
    }


def scan_workspace(root: Path, *, excluded_paths: tuple[Path, ...] = ()) -> dict:
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Workspace root must be a directory")
    omitted = {path.resolve() for path in excluded_paths}
    entries: list[dict] = []
    errors: list[dict] = []
    skipped_links: list[str] = []

    def walk_error(error: OSError) -> None:
        # No absolute paths or source text in error records.
        errors.append({"path": "directory_walk", "kind": type(error).__name__})

    for directory, directories, filenames in os.walk(root, followlinks=False,
                                                     onerror=walk_error):
        parent = Path(directory)
        kept = []
        for name in sorted(directories):
            child = parent / name
            if name in EXCLUDED_DIRECTORIES or name.startswith(".venv"):
                continue
            if child.is_symlink() or not child.resolve().is_relative_to(root):
                skipped_links.append(child.relative_to(root).as_posix())
                continue
            kept.append(name)
        directories[:] = kept
        for name in sorted(filenames):
            path = parent / name
            relative = path.relative_to(root)
            if excluded_file(relative):
                continue
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                skipped_links.append(relative.as_posix())
                continue
            if path.resolve() in omitted:
                continue
            try:
                raw = path.read_bytes()
                entry = {
                    "path": relative.as_posix(), "bytes": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "extension": path.suffix.lower(),
                }
                if path.suffix.lower() == ".py":
                    try:
                        entry["python"] = source_details(raw, relative.as_posix())
                    except (SyntaxError, UnicodeError) as error:
                        issue = {"path": relative.as_posix(),
                                 "kind": type(error).__name__,
                                 "line": getattr(error, "lineno", None)}
                        entry["python_error"] = issue
                        errors.append(issue)
                entries.append(entry)
            except OSError as error:
                errors.append({"path": relative.as_posix(), "kind": type(error).__name__})

    entries.sort(key=lambda entry: entry["path"])
    by_path = {entry["path"]: entry for entry in entries}
    capabilities = {}
    for name, (relative, symbol) in CAPABILITY_EVIDENCE.items():
        entry = by_path.get(relative)
        definitions = entry.get("python", {}).get("definitions", []) if entry else []
        capabilities[name] = {
            "path": relative, "symbol": symbol, "source_present": entry is not None,
            "symbol_present": any(item["name"] == symbol for item in definitions),
            "runtime_verified": False,
        }
    return {
        "schema_version": 1,
        "scope": "first_party_file_inventory_and_python_ast",
        "status": "passed" if not errors else "failed",
        "summary": {
            "files": len(entries),
            "python_files": sum(entry["extension"] == ".py" for entry in entries),
            "by_top_level": dict(sorted(Counter(
                entry["path"].split("/")[0] for entry in entries).items())),
            "by_extension": dict(sorted(Counter(
                entry["extension"] for entry in entries).items())),
        },
        "excluded_directories": sorted(EXCLUDED_DIRECTORIES),
        "skipped_links": sorted(skipped_links),
        "errors": errors,
        "capabilities": capabilities,
        "files": entries,
    }


def runtime_dependencies() -> dict:
    """Probe top-level discovery and metadata without importing dependencies."""
    result = {}
    for module, distribution in DEPENDENCIES.items():
        try:
            discoverable = importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            discoverable = False
        try:
            version = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            version = None
        result[module] = {"discoverable": discoverable, "version": version,
                          "import_verified": False}
    return result


def repository_identity(root: Path) -> dict:
    """Use read-only Git commands; no remote access or credential inspection."""
    result = {}
    for key, arguments in {"commit": ["rev-parse", "HEAD"],
                           "branch": ["branch", "--show-current"]}.items():
        try:
            command = subprocess.run(
                ["git", "-C", str(root), *arguments], capture_output=True,
                text=True, check=False, timeout=5,
            )
            result[key] = command.stdout.strip() if command.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            result[key] = None
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help="JSON path within --root; relative paths resolve against --root")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    output = output.resolve()
    if not output.is_relative_to(root) or output.suffix.lower() != ".json":
        parser.error("Output must be a .json file within the workspace root")
    try:
        report = scan_workspace(root, excluded_paths=(output,))
    except (OSError, ValueError) as error:
        parser.error(f"Cannot scan workspace: {type(error).__name__}")
    try:
        timestamp = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()
    except ZoneInfoNotFoundError:
        # Standard-library-only Windows installations may have no IANA database.
        from datetime import timedelta, timezone

        timestamp = datetime.now(timezone(timedelta(hours=8))).isoformat()
    report.update(
        generated_at=timestamp, repository=repository_identity(root),
        interpreter={"version": sys.version.split()[0],
                     "dependencies": runtime_dependencies()},
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "files": report["summary"]["files"],
                      "python_files": report["summary"]["python_files"],
                      "errors": len(report["errors"]),
                      "output": output.relative_to(root).as_posix()}, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
