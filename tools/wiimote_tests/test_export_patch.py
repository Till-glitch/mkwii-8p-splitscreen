"""Recovery-patch tests in newly created disposable Git repositories only."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

from tools.export_pulsar_patch import ExportError, export, find_git

ROOT = Path(__file__).resolve().parents[2]


class PatchExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.git_executable = find_git()
        if self.git_executable is None:
            self.skipTest("Git executable is unavailable")
        temporary_root = ROOT / "build" / "patch-export-tests"
        temporary_root.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=temporary_root)
        self.directory = Path(self.temporary.name)
        self.repo = self.directory / "source"
        self.repo.mkdir()
        self.output = self.directory / "wheel.patch"
        self.manifest = self.directory / "wheel.json"
        self.git("init", "-q", "--initial-branch=main")
        self.write("PulsarEngine/SplitScreen8/Input.cpp", "// baseline\nint value = 1;\n")
        self.write("GameSource/symbols.txt", "existing = 0x80000000\n")
        self.write(".gitignore", "build/\nignored.hpp\n")
        # Only disposable fixture repositories are staged/committed. The
        # exporter itself never invokes add, commit, update-index or checkout.
        self.git("add", ".")
        self.git("commit", "-q", "-m", "baseline")

    def tearDown(self) -> None:
        if hasattr(self, "temporary"):
            self.temporary.cleanup()

    def git(self, *arguments: str, cwd: Path | None = None) -> bytes:
        result = subprocess.run([self.git_executable, "-C", str(cwd or self.repo),
                                 "-c", "user.name=Patch Export Fixture", "-c", "user.email=fixture@example.invalid",
                                 "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false",
                                 "-c", f"core.hooksPath={self.directory / 'no-hooks'}", *arguments],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
        return result.stdout

    def write(self, path: str, content: str | bytes) -> None:
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)

    def unlink_fixture(self, path: Path) -> None:
        # Windows indexing/antivirus can briefly retain a file after git status.
        # Retry only sharing violations while cleaning a disposable fixture;
        # never retry a failed exporter assertion or alter production behavior.
        for attempt in range(10):
            try:
                path.unlink()
                return
            except PermissionError as exc:
                if getattr(exc, "winerror", None) != 32 or attempt == 9:
                    raise
                time.sleep(0.02)

    def clone_baseline(self) -> Path:
        target = self.directory / "baseline-copy"
        # A newly created tiny fixture can be copied with independent files.
        # This avoids Git-for-Windows invoking an MSYS upload-pack shell for a
        # local clone inside restricted test environments.
        shutil.copytree(self.repo, target)
        return target

    def test_modified_and_new_sources_apply_to_clean_baseline(self) -> None:
        baseline = self.clone_baseline()
        self.write("PulsarEngine/SplitScreen8/Input.cpp", "// baseline\nint value = 2;\n")
        self.write("PulsarEngine/SplitScreen8/WheelBridge.cpp", "void WheelBridgeTick() {}\n")
        self.write("PulsarEngine/SplitScreen8/WheelBridge.hpp", "#pragma once\nvoid WheelBridgeTick();\n")
        self.write("build/ignored.hpp", "ignored generated text\n")
        self.write("ignored.hpp", "ignored source-shaped artifact\n")
        info = export(self.repo, self.output, self.manifest)
        self.assertEqual(len(info["paths"]), 3)
        patch = self.output.read_bytes()
        self.assertIn(b"a/PulsarEngine/SplitScreen8/Input.cpp", patch)
        self.assertIn(b"b/PulsarEngine/SplitScreen8/WheelBridge.cpp", patch)
        self.assertNotIn(str(self.repo).encode(), patch)
        self.git("apply", "--check", str(self.output), cwd=baseline)
        self.git("apply", str(self.output), cwd=baseline)
        for path in info["paths"]:
            self.assertEqual((baseline / path).read_bytes(), (self.repo / path).read_bytes())
        self.assertEqual(json.loads(self.manifest.read_text(encoding="utf-8")), info)

    def test_empty_new_file_spaces_unicode_and_missing_final_newline(self) -> None:
        baseline = self.clone_baseline()
        self.write("PulsarEngine/SplitScreen8/empty.hpp", b"")
        self.write("PulsarEngine/SplitScreen8/space ü.hpp", "// text without newline")
        export(self.repo, self.output, self.manifest)
        self.git("apply", "--check", str(self.output), cwd=baseline)
        self.git("apply", str(self.output), cwd=baseline)
        self.assertEqual((baseline / "PulsarEngine/SplitScreen8/empty.hpp").read_bytes(), b"")
        self.assertEqual((baseline / "PulsarEngine/SplitScreen8/space ü.hpp").read_bytes(), b"// text without newline")

    def test_deleted_tracked_source_and_staged_changes_are_included(self) -> None:
        baseline = self.clone_baseline()
        (self.repo / "GameSource/symbols.txt").unlink()
        self.write("PulsarEngine/SplitScreen8/Input.cpp", "// staged content\n")
        self.git("add", "PulsarEngine/SplitScreen8/Input.cpp")
        self.write("PulsarEngine/SplitScreen8/Input.cpp", "// final working content\n")
        export(self.repo, self.output, self.manifest)
        self.git("apply", str(self.output), cwd=baseline)
        self.assertFalse((baseline / "GameSource/symbols.txt").exists())
        self.assertEqual((baseline / "PulsarEngine/SplitScreen8/Input.cpp").read_text(), "// final working content\n")

    def test_check_is_read_only_and_detects_changed_source(self) -> None:
        self.write("PulsarEngine/SplitScreen8/WheelBridge.hpp", "// first\n")
        export(self.repo, self.output, self.manifest)
        patch_before = self.output.read_bytes()
        metadata_before = self.manifest.read_bytes()
        index = self.repo / ".git" / "index"
        index_before = index.read_bytes()
        index_mtime = index.stat().st_mtime_ns
        export(self.repo, self.output, self.manifest, check=True)
        self.assertEqual(index.read_bytes(), index_before)
        self.assertEqual(index.stat().st_mtime_ns, index_mtime)
        self.write("PulsarEngine/SplitScreen8/WheelBridge.hpp", "// second\n")
        with self.assertRaisesRegex(ExportError, "stale"):
            export(self.repo, self.output, self.manifest, check=True)
        self.assertEqual(self.output.read_bytes(), patch_before)
        self.assertEqual(self.manifest.read_bytes(), metadata_before)

    def test_check_detects_tampered_metadata_or_patch(self) -> None:
        self.write("PulsarEngine/SplitScreen8/WheelBridge.hpp", "// header\n")
        export(self.repo, self.output, self.manifest)
        self.output.write_bytes(self.output.read_bytes() + b"\n")
        with self.assertRaisesRegex(ExportError, "stale"):
            export(self.repo, self.output, self.manifest, check=True)
        export(self.repo, self.output, self.manifest)
        value = json.loads(self.manifest.read_text())
        value["base_commit"] = "0" * 40
        self.manifest.write_text(json.dumps(value))
        with self.assertRaisesRegex(ExportError, "stale"):
            export(self.repo, self.output, self.manifest, check=True)

    def test_unexpected_or_binary_dirty_files_fail_closed(self) -> None:
        for path, data in (("extra.py", b"print('unexpected')\n"),
                           ("Nintendo.szs", b"not admitted even if text"),
                           ("binary.hpp", b"text\0binary"),
                           ("wrong-encoding.cpp", b"\xff\xfe"),
                           ("assets/resource.txt", b"generated asset text")):
            with self.subTest(path=path):
                self.write(path, data)
                with self.assertRaises(ExportError):
                    export(self.repo, self.output, self.manifest)
                self.assertFalse(self.output.exists())
                self.unlink_fixture(self.repo / path)

    def test_modified_binary_tracked_source_fails_closed(self) -> None:
        self.write("PulsarEngine/SplitScreen8/Input.cpp", b"bad\0input")
        with self.assertRaisesRegex(ExportError, "Binary"):
            export(self.repo, self.output, self.manifest)
        self.assertFalse(self.output.exists())

    def test_unexpected_staged_path_is_refused_even_if_working_copy_was_reverted(self) -> None:
        original = (self.repo / ".gitignore").read_bytes()
        self.write(".gitignore", original + b"another-rule/\n")
        self.git("add", ".gitignore")
        self.write(".gitignore", original)
        self.write("PulsarEngine/SplitScreen8/WheelBridge.hpp", "// current source\n")
        with self.assertRaisesRegex(ExportError, "allowlist"):
            export(self.repo, self.output, self.manifest)
        self.assertFalse(self.output.exists())

    def test_clean_tree_and_output_inside_source_are_refused(self) -> None:
        with self.assertRaisesRegex(ExportError, "No current"):
            export(self.repo, self.output, self.manifest)
        self.write("PulsarEngine/SplitScreen8/WheelBridge.hpp", "// header\n")
        with self.assertRaisesRegex(ExportError, "outside"):
            export(self.repo, self.repo / "wheel.patch", self.manifest)


if __name__ == "__main__":
    unittest.main()
