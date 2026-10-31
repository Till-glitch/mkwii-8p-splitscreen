"""Lifecycle and evidence regression tests; no Dolphin, COM or game data is opened."""
from __future__ import annotations

import contextlib
import ctypes
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.wiimote_bridge import runner
from tools.wiimote_bridge.protocol import FLAG_CALIBRATED


class FakeProcess:
    pid = 1234

    def __init__(self):
        self.returncode = None
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def kill(self):
        self.killed = True
        self.returncode = -1

    def wait(self, timeout):
        return self.returncode


class RunnerFixture(unittest.TestCase):
    def setUp(self):
        temporary_root = ROOT / "build/tmp"
        temporary_root.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="runner-test-", dir=temporary_root)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.layout = SimpleNamespace(root=self.root, dolphin=self.root / "Dolphin",
                                      rr=self.root / "Dolphin/Load/Riivolution/SplitScreen8",
                                      launch=self.root / "SplitScreen8.json", pid_file=self.root / "dolphin.pid",
                                      dolphin_log=self.root / "Dolphin/Logs/dolphin.log")
        self.layout.rr.joinpath("Binaries").mkdir(parents=True)
        self.layout.dolphin_log.parent.mkdir(parents=True)
        self.layout.launch.write_text("{}", encoding="utf-8")
        self.layout.dolphin_log.write_text("old log", encoding="utf-8")
        self.code = self.layout.rr / "Binaries/Code.pul"
        self.code.write_bytes(b"test code fixture")
        built = self.root / "compiled"
        built.mkdir()
        built.joinpath("Code.pul").write_bytes(self.code.read_bytes())
        self.manifest = built / "wheel-bridge-manifest.json"
        self.manifest.write_text(json.dumps({"build_id": "01" * 16, "game_id": "RMCP01",
                                             "descriptor_abi": 1, "capabilities": 3, "mode": "wheel-input"}), encoding="utf-8")
        self.exe = self.root / "Dolphin.exe"
        self.exe.write_bytes(b"not executable: never launched by these tests")
        self.process = FakeProcess()
        self.launches = []
        self.alive = {1234: 42}
        self.install = SimpleNamespace(
            Layout=lambda root, vanilla: self.layout,
            recorded_pid=self.recorded_pid,
            dolphin_alive=lambda pid, created: self.alive.get(pid) == created,
            dolphin_exe=lambda: self.exe,
            process_created=lambda pid: self.alive.get(pid))

    def recorded_pid(self, layout):
        try:
            pid, created = layout.pid_file.read_text().split()
            return int(pid), int(created)
        except (OSError, ValueError):
            return None

    def process_factory(self, command, **options):
        self.launches.append((command, options))
        return self.process

    def make_run(self, **kwargs):
        return runner.DolphinRun(self.root, self.manifest, install=self.install,
                                 process_factory=self.process_factory, **kwargs)

    def test_profile_lock_fails_before_log_or_pid_mutation(self):
        self.layout.pid_file.write_text("999 77\n")
        lock = runner.ProfileLock(self.root)
        lock.acquire()
        try:
            with self.assertRaises(runner.RunnerError):
                with self.make_run():
                    self.fail("second invocation must not enter")
            self.assertEqual(self.layout.dolphin_log.read_text(), "old log")
            self.assertEqual(self.layout.pid_file.read_text(), "999 77\n")
            self.assertEqual(self.launches, [])
        finally:
            lock.release()

    def test_existing_profile_process_rejected_before_log_rotation(self):
        self.alive[777] = 88
        self.layout.pid_file.write_text("777 88\n")
        with self.assertRaises(runner.RunnerError):
            with self.make_run():
                pass
        self.assertEqual(self.layout.dolphin_log.read_text(), "old log")
        self.assertEqual(self.layout.pid_file.read_text(), "777 88\n")
        self.assertFalse(self.root.joinpath("lane.lock").exists())
        self.assertEqual(self.launches, [])

    def test_cleanup_stops_only_owned_popen_not_replaced_pid_file(self):
        with self.make_run() as run:
            self.assertEqual(run.pid_record, "1234 42\n")
            self.layout.pid_file.write_text("999 77\n")
        self.assertTrue(self.process.terminated)
        self.assertEqual(self.layout.pid_file.read_text(), "999 77\n")
        self.assertEqual(self.launches[0][1]["cwd"], ROOT)

    def test_normal_cleanup_removes_only_owned_pid_record(self):
        with self.make_run():
            self.assertTrue(self.layout.pid_file.exists())
            self.assertFalse(self.layout.dolphin_log.exists())
        self.assertFalse(self.layout.pid_file.exists())
        archived = list(self.layout.dolphin_log.parent.glob("dolphin.bridge-*.log"))
        self.assertEqual(len(archived), 1)
        self.assertEqual(archived[0].read_text(), "old log")

    def test_native_resolution_override_uses_dolphin_graphics_system_name(self):
        with self.make_run():
            command = self.launches[0][0]
            overrides = [command[i + 1] for i, token in enumerate(command) if token == "-C"]
            self.assertIn("Graphics.Settings.InternalResolution=1", overrides)
            self.assertFalse(any(value.startswith("GFX.") for value in overrides))

    def test_leave_running_is_explicit_and_keeps_pid_record(self):
        with self.make_run(leave_running=True):
            pass
        self.assertFalse(self.process.terminated)
        self.assertEqual(self.layout.pid_file.read_text(), "1234 42\n")

    def test_unverifiable_new_process_is_stopped_even_with_leave_running(self):
        self.install.process_created = lambda pid: None
        with self.assertRaises(runner.RunnerError):
            with self.make_run(leave_running=True):
                pass
        self.assertTrue(self.process.terminated)
        self.assertFalse(self.layout.pid_file.exists())

    def test_manifest_requires_matching_installed_code_before_mutation(self):
        self.code.write_bytes(b"different build")
        with self.assertRaises(runner.RunnerError):
            with self.make_run():
                pass
        self.assertEqual(self.layout.dolphin_log.read_text(), "old log")
        self.assertEqual(self.launches, [])

    def test_unknown_capabilities_or_mode_rejected(self):
        document = json.loads(self.manifest.read_text())
        for change in ({"capabilities": 2}, {"capabilities": 7}, {"mode": "diagnostic"}, {"capabilities": True}):
            self.manifest.write_text(json.dumps({**document, **change}))
            with self.subTest(change=change), self.assertRaises(runner.RunnerError):
                runner.validate_installed_manifest(self.manifest, self.code)

    def test_second_runner_same_profile_rejected_while_first_owns_lock(self):
        with self.make_run():
            with self.assertRaises(runner.RunnerError):
                with self.make_run():
                    pass
            self.assertEqual(len(self.launches), 1)
            self.assertFalse(self.process.terminated)

    def test_malformed_existing_pid_file_not_overwritten(self):
        self.layout.pid_file.write_text("ambiguous")
        with self.assertRaises(runner.RunnerError):
            with self.make_run():
                pass
        self.assertEqual(self.layout.pid_file.read_text(), "ambiguous")
        self.assertEqual(self.layout.dolphin_log.read_text(), "old log")

    def test_replaced_process_identity_fails_alive_check(self):
        with self.make_run() as run:
            self.alive[1234] = 43
            with self.assertRaises(runner.RunnerError):
                run.ensure_alive()

    def test_logged_capability_mismatch_fails_before_memory_open(self):
        with self.make_run() as run:
            self.layout.dolphin_log.write_text("ss8 wheel bridge: descriptor=80300000 session=1234 abi=1 cap=1\n")
            with patch("tools.wiimote_bridge.windows_memory.WindowsProcessMemory") as memory:
                with self.assertRaises(runner.RunnerError):
                    run.connect(timeout=1, gameplay=True)
                memory.assert_not_called()

    def test_ram_aliases_require_current_logged_session(self):
        backend = SimpleNamespace(creation_time=42, mem1_base=1, write_range=None, closed=False)
        backend.close = lambda: setattr(backend, "closed", True)
        attempts = []
        class CandidateMailbox:
            def __init__(self, memory, address, manifest):
                attempts.append(memory.mem1_base)
                self.descriptor = SimpleNamespace(guest_session=0xABCD if memory.mem1_base == 0x22000 else 0xFFFF, capabilities=3)
            def read_status(self):
                return SimpleNamespace(guest_tick=10)
        with self.make_run() as run:
            self.layout.dolphin_log.write_text("ss8 wheel bridge: descriptor=80300000 session=abcd abi=1 cap=3\n")
            with patch("tools.wiimote_bridge.windows_memory.WindowsProcessMemory", return_value=backend), \
                    patch.object(runner, "mem1_candidates", return_value=[0x11000, 0x22000]), \
                    patch.object(runner, "GuestMailbox", CandidateMailbox):
                run.connect(timeout=1, gameplay=True)
            self.assertEqual(run.mem1_base, 0x22000)
            self.assertEqual([alias["valid"] for alias in run.aliases], [False, True])
            self.assertEqual(attempts, [0x11000, 0x22000, 0x22000])
        self.assertTrue(backend.closed)

    def test_reopened_pid_creation_time_must_match_launcher(self):
        backend = SimpleNamespace(creation_time=43, closed=False)
        backend.close = lambda: setattr(backend, "closed", True)
        with self.make_run() as run:
            self.layout.dolphin_log.write_text("ss8 wheel bridge: descriptor=80300000 session=abcd abi=1 cap=3\n")
            with patch("tools.wiimote_bridge.windows_memory.WindowsProcessMemory", return_value=backend), \
                    patch.object(runner, "mem1_candidates") as scan:
                with self.assertRaises(runner.RunnerError):
                    run.connect(timeout=1)
                scan.assert_not_called()
        self.assertTrue(backend.closed)

    def test_serial_child_command_uses_explicit_pid_paths_and_capability(self):
        with self.make_run() as run:
            run.mailbox = SimpleNamespace(descriptor_address=0x80300000)
            run.mem1_base = 0x123400000
            command = runner.serial_command(run, port="COM8", baud=115200, seconds=2, config=self.root / "config.json")
            manual = runner.serial_command(run, port="COM8", baud=115200, seconds=2,
                                           config=self.root / "config.json", manual_mapping=True)
            self.assertNotIn("--manual-mapping", command)
            self.assertIn("--manual-mapping", manual)
            self.assertEqual(command[:4], [sys.executable, "-m", "tools.wiimote_bridge", "--attach"])
            self.assertIn("--drive", command)
            self.assertEqual(command[command.index("--pid") + 1], "1234")
            self.assertEqual(command[command.index("--port") + 1], "COM8")
            self.assertEqual(command[command.index("--manifest") + 1], str(self.manifest))

    def test_all_five_cli_help_commands_work_from_foreign_cwd(self):
        for name in ("run_live_bridge.py", "test_live_bridge.py", "test_player5_join.py", "test_player8_join.py", "test_player8_race.py"):
            with self.subTest(name=name):
                result = subprocess.run([sys.executable, "-B", str(ROOT / "tools" / name), "--help"], cwd=self.root, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("--manifest", result.stdout)
                self.assertIn("--dolphin-exe", result.stdout)


class SyntheticEvidenceTests(unittest.TestCase):
    def test_discovery_reads_small_committed_regions_without_large_mapping_assumption(self):
        class Callable:
            def __init__(self, function):
                self.function = function
            def __call__(self, *arguments):
                return self.function(*arguments)
        reads = []
        def query(handle, address, output, size):
            if address:
                return 0
            region = ctypes.cast(output, ctypes.POINTER(runner.MBI)).contents
            region.BaseAddress = 0x1000
            region.RegionSize = 4096
            region.State = 0x1000
            region.Protect = 4
            return size
        def read(handle, address, output, size, count):
            data = b"RMCP01" if address == 0x1000 else b"\x5d\x1c\x9e\xa3"
            reads.append((address, size))
            ctypes.memmove(output, data, size)
            ctypes.cast(count, ctypes.POINTER(ctypes.c_size_t)).contents.value = size
            return 1
        backend = SimpleNamespace(handle=1, ensure_target=lambda: None,
                                  kernel=SimpleNamespace(VirtualQueryEx=Callable(query), ReadProcessMemory=Callable(read)))
        self.assertEqual(runner.mem1_candidates(backend, deadline=1, clock=lambda: 0), [0x1000])
        self.assertEqual(reads, [(0x1000, 6), (0x1018, 4)])

    def test_calibrated_neutral_sensor_axes_and_independent_slots(self):
        source = runner.SyntheticInputs(1)
        view = source.view([0, 0, 0, 0], 0)
        first = view.slots[0]
        self.assertEqual((first.accel_x, first.accel_y, first.accel_z), (128, 0, 0))
        self.assertTrue(first.flags & FLAG_CALIBRATED)
        self.assertEqual([slot.flags for slot in view.slots[1:]], [0, 0, 0])

    def test_press_release_press_retained_until_matching_guest_ack(self):
        source = runner.SyntheticInputs(4)
        source.view([0, 0, 0, 0], 0)
        source.view([0x900, 0, 0, 0], 1)
        source.view([0, 0, 0, 0], 2)
        view = source.view([0x900, 0x100, 0, 0], 3)
        self.assertEqual([event.event_sequence for event in view.events if event.slot_id == 0], [1, 2, 3])
        status = SimpleNamespace(host_session=99, source_session=source.boot_session, acknowledged_events=(2, 0, 0, 0))
        source.acknowledge(status, host_session=99)
        self.assertEqual([(event.slot_id, event.event_sequence) for event in source.pending], [(0, 3), (1, 1)])
        status.host_session = 100
        status.acknowledged_events = (3, 1, 0, 0)
        source.acknowledge(status, host_session=99)
        self.assertEqual(len(source.pending), 2)

    def test_menu_tick_or_join_mask_alone_never_proves_race(self):
        evidence = runner.RaceEvidence()
        status = SimpleNamespace(bound_player_mask=0xF0, guest_tick=100000, accepted_count=500)
        self.assertFalse(evidence.complete(status))
        status.guest_tick += 1000
        self.assertFalse(evidence.complete(status))

    def race_lines(self):
        return "".join(f"ss8 race player {index}: type 0 hud {index} ch {index} character 0x0 kart 0x0 team 2\n" for index in range(8)) + "ss8 context: gamemode 1 battle 0 course 0x8 race 0\n"

    def test_real_race_markers_still_require_following_tick_and_publication_progress(self):
        evidence = runner.RaceEvidence()
        evidence.feed(self.race_lines())
        status = SimpleNamespace(bound_player_mask=0xF0, guest_tick=100, accepted_count=10)
        self.assertFalse(evidence.complete(status))
        status.guest_tick = 220
        self.assertFalse(evidence.complete(status))
        status.accepted_count = 11
        self.assertTrue(evidence.complete(status))

    def test_later_menu_section_invalidates_prior_race_evidence(self):
        evidence = runner.RaceEvidence()
        for character in self.race_lines():
            evidence.feed(character)
        self.assertTrue(evidence.observed)
        evidence.feed("ss8 section 0x54 frame 10000 locals 8\n")
        self.assertFalse(evidence.observed)

    def test_missing_local_player_or_wrong_gamemode_not_accepted(self):
        for text in (self.race_lines().replace("player 7: type 0", "player 7: type 1"), self.race_lines().replace("gamemode 1", "gamemode 4")):
            evidence = runner.RaceEvidence()
            evidence.feed(text)
            self.assertFalse(evidence.observed)

    def test_manifest_is_mandatory_and_timeout_bounded(self):
        parser = runner.common_parser("test")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args([])
        for value in (0, -1, float("nan"), float("inf"), 901):
            with self.assertRaises(runner.RunnerError):
                runner.check_timeout(value)


if __name__ == "__main__":
    unittest.main()
