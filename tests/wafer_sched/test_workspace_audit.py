"""Stage-one tests run without pytest or the platform's live-workspace fixtures."""

import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/63_audit_wafer_workspace.py"
SPEC = importlib.util.spec_from_file_location("wafer_workspace_audit", SCRIPT)
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class WorkspaceAuditTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wafer-audit-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_parses_all_python_without_executing_project_code(self):
        source = (
            "import nonexistent_dependency\nfrom imaginary import solver\n"
            "class Equipment: pass\nasync def simulate(): pass\n"
            "raise RuntimeError('must never execute this source')\n"
        )
        path = self.write("src/device.py", source)
        self.write("frontend/src/view.tsx", "export const view = 'equipment';\n")
        report = AUDIT.scan_workspace(self.root)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["summary"]["files"], 2)
        self.assertEqual(report["summary"]["python_files"], 1)
        entry = next(item for item in report["files"] if item["path"] == "src/device.py")
        self.assertEqual(entry["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(entry["python"]["imports"], ["imaginary", "nonexistent_dependency"])
        self.assertEqual([item["name"] for item in entry["python"]["definitions"]],
                         ["Equipment", "simulate"])

    def test_excludes_credentials_runtime_virtualenv_and_generated_output(self):
        for name in (".env", ".env.local", "config/workspaces.local.json", "secrets.json",
                     ".aws/credentials", "storage/live.py", "outputs/run/result.json",
                     "results/experiment/metrics.json", ".venv_custom/private.py",
                     "frontend/node_modules/pkg/index.js", "docs/workspace_inventory.json"):
            self.write(name, "sensitive-or-runtime-content")
        self.write("configs/static.json", '{"chambers": 2}')
        report = AUDIT.scan_workspace(self.root)
        self.assertEqual([entry["path"] for entry in report["files"]], ["configs/static.json"])

    def test_reports_syntax_and_encoding_errors_without_source_leakage(self):
        self.write("broken.py", "def private_secret(\n")
        (self.root / "encoding.py").write_bytes(b"\xff")
        report = AUDIT.scan_workspace(self.root)
        self.assertEqual(report["status"], "failed")
        self.assertEqual({issue["kind"] for issue in report["errors"]},
                         {"SyntaxError", "UnicodeDecodeError"})
        self.assertNotIn("private_secret", json.dumps(report))

    def test_existing_symbols_are_static_evidence_only(self):
        self.write("api/domains/registry.py", "class DomainRegistry: pass\n")
        capability = AUDIT.scan_workspace(self.root)["capabilities"]["domain_registration"]
        self.assertTrue(capability["source_present"])
        self.assertTrue(capability["symbol_present"])
        self.assertFalse(capability["runtime_verified"])
        self.write("api/domains/registry.py", "class DifferentRegistry: pass\n")
        capability = AUDIT.scan_workspace(self.root)["capabilities"]["domain_registration"]
        self.assertFalse(capability["symbol_present"])

    def test_cli_output_is_repeatable_and_excludes_itself(self):
        self.write("equipment.py", "class Equipment: pass\n")
        arguments = ["--root", str(self.root), "--output", "audit/inventory.json"]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(AUDIT.main(arguments), 0)
        output = self.root / "audit/inventory.json"
        first = json.loads(output.read_text(encoding="utf-8"))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(AUDIT.main(arguments), 0)
        second = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(first["files"], second["files"])
        self.assertEqual(second["summary"]["files"], 1)
        self.assertTrue(second["generated_at"].endswith("+08:00"))

    def test_cli_failure_is_not_reported_as_success(self):
        self.write("broken.py", "def invalid syntax:\n")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(AUDIT.main(["--root", str(self.root)]), 1)
        output = self.root / "docs/workspace_inventory.json"
        self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["status"], "failed")

    def test_rejects_output_outside_workspace_and_non_json(self):
        for target in (str(self.root.parent / "outside.json"), "equipment.py"):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                AUDIT.main(["--root", str(self.root), "--output", target])
            self.assertEqual(error.exception.code, 2)

    def test_symlinked_sources_and_directories_are_not_read(self):
        outside_dir = tempfile.TemporaryDirectory(prefix="wafer-audit-outside-")
        self.addCleanup(outside_dir.cleanup)
        outside = Path(outside_dir.name)
        (outside / "sensitive.py").write_text("def invalid syntax:\n", encoding="utf-8")
        try:
            (self.root / "linked.py").symlink_to(outside / "sensitive.py")
            (self.root / "linked_dir").symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("Creating symlinks requires OS support or Windows developer privileges")
        report = AUDIT.scan_workspace(self.root)
        self.assertEqual(report["summary"]["files"], 0)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["skipped_links"], ["linked.py", "linked_dir"])


if __name__ == "__main__":
    unittest.main()
