"""Owned-profile Dolphin lifecycle and explicit synthetic/live bridge smokes.

Nothing starts on import. Launching requires an existing isolated profile and an
explicit manifest whose neighbouring Code.pul matches the installed code.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time

from .mailbox import BuildManifest, GuestMailbox, MailboxBusyError, MailboxError
from .ports import PortSelectionError, available_ports, choose_port
from .protocol import FLAG_CALIBRATED, FLAG_CONNECTED, FLAG_SAMPLE_VALID, EventKind, InputEvent, SnapshotSlot
from .service import HostView

ROOT = Path(__file__).resolve().parents[2]
DESCRIPTOR_RE = re.compile(r"ss8 wheel bridge:.*?descriptor=([0-9a-fA-F]+)\s+session=([0-9a-fA-F]+)\s+abi=(\d+)\s+cap=(\d+)")


class RunnerError(RuntimeError):
    pass


def _installer():
    from tools import install_8p
    return install_8p


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_installed_manifest(path: Path, installed_code: Path) -> tuple[BuildManifest, int]:
    """Read-only preflight; a first-existing output directory is never selected."""
    manifest = BuildManifest.load(path)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        capabilities = document["capabilities"]
        if isinstance(capabilities, bool) or capabilities not in (1, 3):
            raise ValueError("expected known capabilities 1 or 3")
        if document.get("mode") != ("wheel-input" if capabilities == 3 else "diagnostic"):
            raise ValueError("capabilities/mode mismatch")
        built_code = path.with_name("Code.pul")
        if not installed_code.is_file() or not built_code.is_file():
            raise ValueError("both installed Code.pul and the manifest's neighbouring Code.pul are required")
        if sha256(installed_code) != sha256(built_code):
            raise ValueError("installed Code.pul differs from the explicitly selected build")
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise RunnerError(f"Cannot verify installed bridge build: {error}") from error
    return manifest, capabilities


class ProfileLock:
    """Shares lane.py's lock name; fail closed even for an ambiguous stale lock."""

    def __init__(self, root: Path):
        self.path = root / "lane.lock"
        self.token = str(os.getpid())
        self.held = False

    def acquire(self):
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as error:
            raise RunnerError(f"Profile is locked: {self.path}. Check its owner before removing a stale lock.") from error
        try:
            os.write(descriptor, self.token.encode("ascii"))
        finally:
            os.close(descriptor)
        self.held = True

    def release(self):
        if self.held:
            try:
                if self.path.read_text(encoding="ascii") == self.token:
                    self.path.unlink()
            except FileNotFoundError:
                pass
            self.held = False


class MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", ctypes.c_uint32), ("alignment1", ctypes.c_uint32),
                ("RegionSize", ctypes.c_size_t), ("State", ctypes.c_uint32),
                ("Protect", ctypes.c_uint32), ("Type", ctypes.c_uint32), ("alignment2", ctypes.c_uint32)]


def mem1_candidates(backend, *, deadline: float, clock=time.monotonic) -> list[int]:
    """Bounded, read-only scan of the selected handle, including split RAM views."""
    kernel = backend.kernel
    kernel.VirtualQueryEx.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
    kernel.VirtualQueryEx.restype = ctypes.c_size_t
    candidates = []
    address = 0
    for _ in range(100000):
        if clock() >= deadline:
            raise RunnerError("MEM1 discovery timed out before enumeration completed")
        backend.ensure_target()
        region = MBI()
        if not kernel.VirtualQueryEx(backend.handle, address, ctypes.byref(region), ctypes.sizeof(region)):
            break
        base = region.BaseAddress or 0
        end = base + region.RegionSize
        if end <= address:
            raise RunnerError("Invalid virtual-memory region during MEM1 discovery")
        if region.State == 0x1000 and region.RegionSize >= 4096 and not (region.Protect & 0x101):
            magic = ctypes.create_string_buffer(6)
            marker = ctypes.create_string_buffer(4)
            count = ctypes.c_size_t()
            if (kernel.ReadProcessMemory(backend.handle, base, magic, 6, ctypes.byref(count)) and count.value == 6
                    and magic.raw == b"RMCP01"
                    and kernel.ReadProcessMemory(backend.handle, base + 0x18, marker, 4, ctypes.byref(count))
                    and count.value == 4 and marker.raw == b"\x5d\x1c\x9e\xa3"):
                candidates.append(base)
        address = end
        if address >= 0x7FFFFFFFFFFF:
            break
    else:
        raise RunnerError("MEM1 discovery exceeded its region budget")
    return candidates


class DolphinRun:
    def __init__(self, root: Path, manifest_path: Path, *, executable: Path | None = None,
                 leave_running: bool = False, install=None, process_factory=subprocess.Popen):
        self.install = install or _installer()
        self.layout = self.install.Layout(root.resolve(), vanilla=True)
        self.manifest_path = manifest_path.resolve()
        self.executable = executable
        self.leave_running = leave_running
        self.process_factory = process_factory
        self.lock = ProfileLock(self.layout.root)
        self.proc = None
        self.created = None
        self.pid_record = None
        self.backend = None
        self.mailbox = None
        self.aliases = []
        self.log_offset = 0
        self.log_text = ""
        self.mem1_base = None

    def __enter__(self):
        self.lock.acquire()
        try:
            record = self.install.recorded_pid(self.layout)
            if record is not None and self.install.dolphin_alive(*record):
                raise RunnerError(f"This profile already has a running Dolphin PID {record[0]}")
            if self.layout.pid_file.exists() and record is None:
                raise RunnerError("Existing dolphin.pid is malformed; refusing to overwrite it")
            self.manifest, self.capabilities = validate_installed_manifest(
                self.manifest_path, self.layout.rr / "Binaries/Code.pul")
            selected = self.executable or self.install.dolphin_exe()
            if selected is None:
                raise RunnerError("Select Dolphin with --dolphin-exe or configure its path in the installer")
            self.executable = Path(selected).resolve(strict=True)
            if self.executable.name.lower() != "dolphin.exe":
                raise RunnerError("The selected executable must be Dolphin.exe")
            if not self.layout.launch.is_file():
                raise RunnerError("Isolated launch descriptor missing; run install_8p.py prepare first")
            if self.layout.dolphin_log.exists():
                archive = self.layout.dolphin_log.with_name(f"dolphin.bridge-{time.time_ns()}.log")
                self.layout.dolphin_log.replace(archive)  # A failed rotation aborts before launch.
            command = [str(self.executable), "-u", str(self.layout.dolphin),
                       "-C", "Graphics.Settings.InternalResolution=1", "-e", str(self.layout.launch)]
            self.proc = self.process_factory(command, cwd=ROOT)
            self.created = self.install.process_created(self.proc.pid)
            if self.created is None or not self.install.dolphin_alive(self.proc.pid, self.created):
                raise RunnerError("Cannot verify the just-started Dolphin process")
            self.pid_record = f"{self.proc.pid} {self.created}\n"
            self.layout.pid_file.write_text(self.pid_record, encoding="utf-8")
            return self
        except BaseException:
            self.close()
            raise

    def ensure_alive(self):
        if (self.proc is None or self.proc.poll() is not None or self.created is None
                or not self.install.dolphin_alive(self.proc.pid, self.created)):
            raise RunnerError("The Dolphin process started for this run has exited or changed identity")

    def poll_log(self) -> str:
        self.ensure_alive()
        if not self.layout.dolphin_log.exists():
            return ""
        if self.layout.dolphin_log.stat().st_size < self.log_offset:
            raise RunnerError("Current run's Dolphin log was truncated/replaced")
        with self.layout.dolphin_log.open("rb") as source:
            source.seek(self.log_offset)
            raw = source.read(256 * 1024)
            self.log_offset = source.tell()
        text = raw.decode("utf-8", errors="replace")
        self.log_text = (self.log_text + text)[-2 * 1024 * 1024:]
        return text

    def connect(self, timeout: float = 45, *, gameplay: bool = False):
        from .windows_memory import WindowsProcessMemory
        deadline = time.monotonic() + timeout
        match = None
        while time.monotonic() < deadline:
            self.poll_log()
            match = DESCRIPTOR_RE.search(self.log_text)
            if match:
                break
            time.sleep(0.1)
        if match is None:
            raise RunnerError("No descriptor marker from this launch before timeout")
        address, session, abi, capabilities = (int(match[1], 16), int(match[2], 16), int(match[3]), int(match[4]))
        if abi != 1 or capabilities != self.capabilities or (gameplay and capabilities != 3):
            raise RunnerError("Logged descriptor capabilities/ABI differ from the selected build or requested gameplay")
        self.ensure_alive()
        backend = WindowsProcessMemory(self.proc.pid, self.executable, mem1_base=1)
        try:
            if backend.creation_time != self.created:
                raise RunnerError("PID creation time differs from the process launched by this runner")
            candidates = mem1_candidates(backend, deadline=deadline)
            valid = []
            for base in candidates:
                backend.mem1_base = base
                backend.write_range = None
                try:
                    mailbox = GuestMailbox(backend, address, self.manifest)
                    if mailbox.descriptor.guest_session != session or mailbox.descriptor.capabilities != self.capabilities:
                        raise MailboxError("Descriptor does not belong to the logged session/capabilities")
                    status = mailbox.read_status()
                    valid.append(base)
                    self.aliases.append({"base": hex(base), "valid": True, "guest_tick": status.guest_tick})
                except MailboxError as error:
                    self.aliases.append({"base": hex(base), "valid": False, "error": str(error)})
            if not valid:
                raise RunnerError("No MEM1 alias validates the current build, session and status (MEM2 mappings are not guessed)")
            backend.mem1_base = valid[0]
            backend.write_range = None
            self.mailbox = GuestMailbox(backend, address, self.manifest)
            if self.mailbox.descriptor.guest_session != session or self.mailbox.descriptor.capabilities != self.capabilities:
                raise RunnerError("Guest changed during attachment")
            self.backend = backend
            self.mem1_base = valid[0]
            return self.mailbox
        except BaseException:
            backend.close()
            raise

    def screenshot(self, label: str) -> dict:
        self.ensure_alive()
        target = self.layout.root / "shots"
        target.mkdir(parents=True, exist_ok=True)
        try:
            written, refused = self.install.save_shots(self.layout, self.proc.pid, target, label)
            return {"label": label, "written": written, "refused": refused, "manual_review_required": True}
        except Exception as error:
            return {"label": label, "error": str(error), "manual_review_required": True}

    def report(self, name: str, contents: dict):
        data = {"pid": self.proc.pid, "process_created": self.created,
                "manifest": str(self.manifest_path), "build_id": self.manifest.build_id.hex(),
                "capabilities": self.capabilities, "memory_aliases": self.aliases, **contents}
        (self.layout.root / name).write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")

    def close(self):
        try:
            if self.backend is not None:
                self.backend.close()
                self.backend = None
            # Popen keeps the handle of precisely the process started here.
            # Never ask install_8p stop to interpret a mutable dolphin.pid file.
            if self.proc is not None and (not self.leave_running or self.pid_record is None) and self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait(timeout=5)
            if self.proc is not None and self.proc.poll() is not None and self.pid_record is not None:
                try:
                    if self.layout.pid_file.read_text(encoding="utf-8") == self.pid_record:
                        self.layout.pid_file.unlink()
                except FileNotFoundError:
                    pass
        finally:
            self.lock.release()

    def __exit__(self, *_):
        self.close()


def common_parser(description: str, *, timeout: float = 45) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--root", type=Path, default=ROOT / "build/dev-vanilla")
    parser.add_argument("--manifest", type=Path, required=True, help="Explicit build manifest; neighbouring Code.pul must match the installed code")
    parser.add_argument("--dolphin-exe", type=Path, help="Dolphin executable; default is the installer's configured path")
    parser.add_argument("--timeout", type=float, default=timeout)
    parser.add_argument("--leave-running", action="store_true")
    return parser


def check_timeout(value: float):
    if not math.isfinite(value) or not 0 < value <= 900:
        raise RunnerError("Timeout must be finite and between 0 and 900 seconds")


def serial_command(run: DolphinRun, *, port: str, baud: int, seconds: float, config: Path,
                   manual_mapping: bool = False) -> list[str]:
    if baud <= 0 or not math.isfinite(seconds) or seconds < 0:
        raise RunnerError("Invalid serial baud rate or duration")
    return [sys.executable, "-m", "tools.wiimote_bridge", "--attach",
            *(["--manual-mapping"] if manual_mapping else []),
            *(["--drive"] if run.capabilities & 2 else []), "--port", port, "--baud", str(baud),
            "--pid", str(run.proc.pid), "--dolphin-exe", str(run.executable),
            "--descriptor", hex(run.mailbox.descriptor_address), "--mem1-base", hex(run.mem1_base),
            "--manifest", str(run.manifest_path), "--config", str(config.resolve()), "--seconds", str(seconds)]


def run_serial_child(run: DolphinRun, *, port: str | None, baud: int, seconds: float, config: Path,
                     manual_mapping: bool = False) -> int:
    chosen = choose_port(available_ports(), port)
    command = serial_command(run, port=chosen.device, baud=baud, seconds=seconds, config=config,
                             manual_mapping=manual_mapping)
    print(f"Starting serial bridge on {chosen.device}; device count and input state are reported by the service.")
    child = subprocess.Popen(command, cwd=ROOT)
    try:
        while child.poll() is None:
            run.ensure_alive()
            time.sleep(0.1)
        return child.returncode
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)


class SyntheticInputs:
    """A labelled test source: ordered button changes retained until guest ACK."""
    def __init__(self, count: int):
        if not 1 <= count <= 4:
            raise ValueError("synthetic slot count must be 1..4")
        self.count = count
        self.boot_session = secrets.randbits(32) or 1
        self.sample_sequence = 0
        self.buttons = [0] * 4
        self.event_sequence = [0] * 4
        self.pending = []

    def acknowledge(self, status, *, host_session: int):
        if status.host_session != host_session or status.source_session != self.boot_session:
            return
        def newer(value, previous):
            return 0 < ((value - previous) & 0xFFFFFFFF) < 0x80000000
        self.pending = [item for item in self.pending if newer(item.event_sequence, status.acknowledged_events[item.slot_id])]

    def view(self, desired: list[int], now_ms: int, *, steer_y: int = 0) -> HostView:
        self.sample_sequence = (self.sample_sequence + 1) & 0xFFFFFFFF
        for index in range(self.count):
            if desired[index] != self.buttons[index]:
                self.buttons[index] = desired[index]
                self.event_sequence[index] = (self.event_sequence[index] + 1) & 0xFFFFFFFF
                self.pending.append(InputEvent(index, EventKind.BUTTONS, desired[index], self.event_sequence[index], self.sample_sequence, now_ms & 0xFFFFFFFF))
        if len(self.pending) > 32:
            raise RunnerError("Synthetic input queue exceeded 32 unacknowledged events; aborting")
        slots = tuple(SnapshotSlot(i, FLAG_CONNECTED | FLAG_CALIBRATED | FLAG_SAMPLE_VALID if i < self.count else 0,
                                   self.buttons[i], 128 if i < self.count else 0,
                                   steer_y * (1 if i % 2 == 0 else -1) if i < self.count else 0, 0,
                                   0 if i < self.count else 0xFFFF, self.sample_sequence,
                                   self.event_sequence[i], 0) for i in range(4))
        return HostView(self.boot_session, slots, tuple(self.pending), tuple(range(5, 5 + self.count)), ())


class RaceEvidence:
    """RaceFrameHook markers plus fresh progress; a large menu tick is insufficient."""
    def __init__(self):
        self.players = set()
        self.context = False
        self.partial = ""
        self.start_tick = None
        self.start_accepted = None

    def feed(self, text: str):
        text = self.partial + text
        lines = text.split("\n")
        self.partial = lines.pop()
        if len(self.partial) > 65536:
            raise RunnerError("Unexpected oversized Dolphin log line")
        for line in lines:
            if "ss8 section " in line:
                self.players.clear()
                self.context = False
                self.start_tick = self.start_accepted = None
            player = re.search(r"ss8 race player (\d+): type (\d+) hud (-?\d+)", line)
            if player and int(player[2]) == 0 and int(player[1]) == int(player[3]) and int(player[1]) < 8:
                self.players.add(int(player[1]))
            if re.search(r"ss8 context: gamemode 1 battle \d+ course 0x[0-9a-fA-F]+ race \d+", line):
                self.context = True

    @property
    def observed(self):
        return self.context and self.players == set(range(8))

    def complete(self, status) -> bool:
        if not self.observed or status.bound_player_mask & 0xF0 != 0xF0:
            return False
        if self.start_tick is None:
            self.start_tick, self.start_accepted = status.guest_tick, status.accepted_count
            return False
        ticks = (status.guest_tick - self.start_tick) & 0xFFFFFFFF
        accepted = (status.accepted_count - self.start_accepted) & 0xFFFFFFFF
        return 120 <= ticks < 0x80000000 and 0 < accepted < 0x80000000


def run_synthetic_smoke(args, *, count: int, race: bool = False) -> int:
    check_timeout(args.timeout)
    with DolphinRun(args.root, args.manifest, executable=args.dolphin_exe, leave_running=args.leave_running) as run:
        mailbox = run.connect(min(args.timeout, 45), gameplay=True)
        source = SyntheticInputs(count)
        evidence = RaceEvidence()
        evidence.feed(run.log_text)
        started = time.monotonic()
        deadline = started + args.timeout
        status = None
        target_mask = ((1 << count) - 1) << 4
        joined_tick = None
        ever_joined = False
        verified = False
        shots = []
        print(f"Synthetic input smoke: {count} additional slots. No serial device or physical Wiimote is exercised.")
        while time.monotonic() < deadline:
            run.ensure_alive()
            evidence.feed(run.poll_log())
            now_ms = int((time.monotonic() - started) * 1000)
            try:
                latest = mailbox.read_status()
            except MailboxBusyError:
                latest = None
            if latest is not None and latest.host_session == mailbox.host_session and latest.source_session == source.boot_session:
                status = latest
                if status.last_error:
                    raise RunnerError(f"Guest rejected synthetic input: error {status.last_error}")
                source.acknowledge(status, host_session=mailbox.host_session)
                joined = status.bound_player_mask & target_mask == target_mask
                if joined:
                    ever_joined = True
                    if joined_tick is None:
                        joined_tick = status.guest_tick
                    if not race and 2 <= ((status.guest_tick - joined_tick) & 0xFFFFFFFF) < 0x80000000:
                        verified = True
                        break
                    if race and evidence.complete(status):
                        verified = True
                        break
                else:
                    joined_tick = None
            tick = status.guest_tick if status is not None else 0
            mask = status.bound_player_mask if status is not None else 0
            desired = [0] * 4
            if tick > 600 or now_ms > 20000:
                if not ever_joined:
                    desired = [0x0900 if i < count and not (mask & (1 << (4 + i))) else 0 for i in range(4)]
                elif race:
                    if evidence.observed or tick >= 9000:
                        desired = [0x0100] * count + [0] * (4 - count)
                    elif 5300 <= tick < 6050 or 6200 <= tick < 6800 or 7000 <= tick < 7600:
                        desired = [0x0900 if (tick // 6) % 2 == 0 else 0] * count + [0] * (4 - count)
            mailbox.publish(source.view(desired, now_ms, steer_y=60 if evidence.observed else 0), host_elapsed_ms=now_ms)
            time.sleep(0.02)
        shots.append(run.screenshot("synthetic-race-observation" if race else "synthetic-join-observation"))
        run.report("synthetic-race-report.json" if race else f"synthetic-{count + 4}p-join-report.json", {
            "source": "synthetic snapshots and ordered button events; no physical devices",
            "verified": verified, "binding_observed": ever_joined, "race_frame_markers_observed": evidence.observed,
            "race_progress_verified": bool(race and verified), "physical_wheels_verified": False,
            "native_steering_parity_verified": False, "fps_verified": False,
            "status": status.__dict__ if status is not None else None, "screenshots": shots})
        if not verified:
            print("Smoke incomplete: required binding/race evidence was not observed. Screenshot needs manual review.", file=sys.stderr)
            return 6
        if race:
            print("PASS: synthetic eight-player binding and VS race-scene markers with subsequent guest progress. Physical input and kart motion are not automatically verified.")
        else:
            print(f"PASS: synthetic P5–P{4 + count} binding only. Character selection and later transitions were not automatically assessed.")
        return 0
