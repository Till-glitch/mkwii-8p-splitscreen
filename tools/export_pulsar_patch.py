#!/usr/bin/env python3
"""Export uncommitted Pulsar source changes without modifying its Git metadata.

This is a development recovery artifact. It does not replace a published,
reachable submodule commit or turn a dirty checkout into a clean release.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import difflib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPO = ROOT / "external" / "rr-pulsar"
DEFAULT_OUTPUT = ROOT / "patches" / "rr-pulsar-wheel-bridge.patch"
ALLOWED_SUFFIXES = {".cpp", ".hpp", ".h", ".s", ".txt", ".md"}
FORBIDDEN_COMPONENTS = {".git", "build", "dist", "assets", "cache", ".pio", ".venv", "node_modules"}
MAX_SOURCE_BYTES = 16 * 1024 * 1024


class ExportError(RuntimeError):
    pass


def find_git() -> str | None:
    preferred = Path(r"C:\Program Files\Git\cmd\git.exe")
    if preferred.is_file():
        return str(preferred)
    return shutil.which("git")


class Git:
    def __init__(self, repo: Path) -> None:
        executable = find_git()
        if executable is None:
            raise ExportError("Git was not found. Put a working Git executable in PATH first.")
        self.executable = executable
        self.repo = repo.resolve()
        self.environment = os.environ.copy()
        # Git status must not opportunistically refresh/write the real index.
        self.environment["GIT_OPTIONAL_LOCKS"] = "0"

    def run(self, *arguments: str) -> bytes:
        command = [self.executable, "-C", str(self.repo), "--no-pager", "-c", "core.fsmonitor=false",
                   "-c", "core.quotepath=false", "-c", "core.autocrlf=false", *arguments]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env=self.environment, check=False)
        if result.returncode:
            reason = result.stderr.decode("utf-8", errors="replace").strip()
            raise ExportError(f"Git failed ({self.executable}): {reason or 'no error text'}. "
                              "Verify the submodule is initialized and Git can read its metadata.")
        return result.stdout


def _paths(data: bytes) -> tuple[str, ...]:
    try:
        return tuple(sorted(part.decode("utf-8") for part in data.split(b"\0") if part))
    except UnicodeDecodeError as exc:
        raise ExportError("Only UTF-8 source paths can be exported") from exc


def _check_path(path: str) -> None:
    normalized = PurePosixPath(path)
    if (normalized.is_absolute() or ".." in normalized.parts or not normalized.parts
            or any(character in path for character in ('\n', '\r', '\t', '\\', '"'))):
        raise ExportError(f"Unsafe source path: {path!r}")
    if any(part.casefold() in FORBIDDEN_COMPONENTS for part in normalized.parts):
        raise ExportError(f"Build/generated/asset path is not exportable: {path}")
    if normalized.suffix.casefold() not in ALLOWED_SUFFIXES:
        raise ExportError(f"Dirty path is outside the source allowlist: {path}. "
                          "Only .cpp, .hpp, .h, .S, .txt and .md are accepted.")


def _check_text(data: bytes, path: str) -> str:
    if len(data) > MAX_SOURCE_BYTES or b"\0" in data:
        raise ExportError(f"Binary or excessively large source refused: {path}")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ExportError(f"Source is not UTF-8 text: {path}") from exc


@dataclass(frozen=True)
class SourceState:
    base_commit: str
    status: bytes
    tracked: tuple[str, ...]
    untracked: tuple[str, ...]
    contents: tuple[tuple[str, bytes | None, int], ...]


def capture_state(git: Git) -> SourceState:
    top = Path(git.run("rev-parse", "--show-toplevel").decode("utf-8").strip()).resolve()
    if top != git.repo:
        raise ExportError("--repo must name the root of the intended Pulsar repository")
    base = git.run("rev-parse", "--verify", "HEAD").decode("ascii").strip()
    tracked = _paths(git.run("diff", "--no-ext-diff", "--no-textconv", "--no-renames", "--name-only", "-z", "HEAD", "--"))
    untracked = _paths(git.run("ls-files", "--others", "--exclude-standard", "-z"))
    status = git.run("status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignore-submodules=none")
    index_dirty = _paths(git.run("diff", "--cached", "--no-ext-diff", "--no-textconv", "--no-renames", "--name-only", "-z", "--"))
    work_dirty = _paths(git.run("diff", "--no-ext-diff", "--no-textconv", "--no-renames", "--name-only", "-z", "--"))
    for path in set(tracked) | set(untracked) | set(index_dirty) | set(work_dirty):
        _check_path(path)
    # A staged change undone in the working tree is intentionally absent from
    # diff HEAD: this artifact reconstructs the current working tree, not index.
    if not tracked and not untracked:
        raise ExportError("No current working-tree source changes exist to export")
    contents: list[tuple[str, bytes | None, int]] = []
    for path in sorted(set(tracked) | set(untracked)):
        target = git.repo / path
        if target.is_symlink() or not target.resolve().is_relative_to(git.repo):
            raise ExportError(f"Symlink or source outside the repository refused: {path}")
        if target.exists():
            if not target.is_file():
                raise ExportError(f"Directory/submodule is not an exportable source: {path}")
            data = target.read_bytes()
            _check_text(data, path)
            mode = 0o100755 if os.name != "nt" and target.stat().st_mode & stat.S_IXUSR else 0o100644
            contents.append((path, data, mode))
        else:
            if path in untracked:
                raise ExportError(f"Untracked source disappeared while reading: {path}")
            contents.append((path, None, 0))
        if path in tracked:
            entry = git.run("ls-tree", "-z", "HEAD", "--", f":(literal){path}")
            if entry:
                info = entry.split(b"\t", 1)[0].split()
                if len(info) != 3 or info[0] not in (b"100644", b"100755") or info[1] != b"blob":
                    raise ExportError(f"Non-regular tracked source refused: {path}")
                _check_text(git.run("cat-file", "blob", info[2].decode("ascii")), f"HEAD:{path}")
    return SourceState(base, status, tracked, untracked, tuple(contents))


def _quote(path: str) -> str:
    # Always quoted UTF-8 paths are accepted by git apply, including spaces.
    return json.dumps(path, ensure_ascii=False)


def _new_file_patch(path: str, data: bytes, mode: int) -> bytes:
    text = _check_text(data, path)
    old, new = _quote(f"a/{path}"), _quote(f"b/{path}")
    prefix = f"diff --git {old} {new}\nnew file mode {mode:o}\n"
    if not text:
        # A new-file mode alone creates an empty file with git apply.
        return prefix.encode("utf-8")
    lines = list(difflib.unified_diff([], text.splitlines(keepends=True),
                                    fromfile="/dev/null", tofile=new, n=3))
    output = prefix
    for line in lines:
        if line.endswith("\n"):
            output += line
        else:
            output += line + "\n\\ No newline at end of file\n"
    return output.encode("utf-8")


def make_patch(git: Git, state: SourceState) -> bytes:
    patch = b""
    if state.tracked:
        patch = git.run("diff", "--no-ext-diff", "--no-textconv", "--no-renames",
                        "--src-prefix=a/", "--dst-prefix=b/", "HEAD", "--",
                        *(f":(literal){path}" for path in state.tracked))
    sources = {path: (data, mode) for path, data, mode in state.contents}
    for path in state.untracked:
        data, mode = sources[path]
        assert data is not None
        patch += _new_file_patch(path, data, mode)
    _check_text(patch, "generated patch")
    if any(line.startswith((b"GIT binary patch", b"Binary files ")) for line in patch.splitlines()):
        raise ExportError("Git produced binary patch content; export refused")
    return patch


def metadata(state: SourceState, patch: bytes) -> dict[str, object]:
    return {"format_version": 1, "base_commit": state.base_commit,
            "patch_sha256": hashlib.sha256(patch).hexdigest(),
            "paths": sorted(set(state.tracked) | set(state.untracked)),
            "new_files": list(state.untracked)}


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
            temporary = handle.name
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def export(repo: Path, output: Path, manifest: Path, *, check: bool = False) -> dict[str, object]:
    git = Git(repo)
    for target in (output, manifest):
        if target.is_symlink() or target.resolve().is_relative_to(git.repo):
            raise ExportError("Patch and metadata outputs must be outside the source repository and cannot be symlinks")
    if output.resolve() == manifest.resolve():
        raise ExportError("Patch and metadata must use different paths")
    state = capture_state(git)
    patch = make_patch(git, state)
    if capture_state(git) != state:
        raise ExportError("Source checkout changed during export; retry after edits have finished")
    info = metadata(state, patch)
    if check:
        try:
            actual_patch = output.read_bytes()
            actual_metadata = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ExportError(f"Cannot check patch/metadata: {exc}. Run export without --check first.") from exc
        if actual_patch != patch or actual_metadata != info:
            raise ExportError("Patch or metadata is stale; rerun export after finishing the current source edits")
    else:
        _atomic_write(output, patch)
        _atomic_write(manifest, (json.dumps(info, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    return info


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO, help="Initialized source repository root")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Patch output outside the source repository")
    parser.add_argument("--metadata", type=Path, help="Metadata JSON (default: output with .json suffix)")
    parser.add_argument("--check", action="store_true", help="Read-only: verify patch and metadata match the current sources")
    args = parser.parse_args(argv)
    try:
        info = export(args.repo, args.output, args.metadata or args.output.with_suffix(".json"), check=args.check)
    except (ExportError, OSError) as exc:
        print(f"Patch export error: {exc}", file=sys.stderr)
        return 2
    print(f"{'Verified' if args.check else 'Exported'} {len(info['paths'])} source files against {info['base_commit']}")
    print(f"Patch: {args.output}\nSHA256: {info['patch_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
