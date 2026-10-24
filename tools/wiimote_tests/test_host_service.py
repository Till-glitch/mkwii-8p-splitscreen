"""Host-only tests: no serial device, Dolphin, or optional dependency imports."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools.wiimote_bridge.mapping import DeviceRegistry, MappingError, normalize_mac
from tools.wiimote_bridge.ports import PortInfo, PortSelectionError, choose_port
from tools.wiimote_bridge.protocol import (DeviceRecord, EventKind, Frame, InputEvent,
                                           MessageKind, SnapshotSlot, encode_frame)
from tools.wiimote_bridge.recording import RecordingError, RecordingWriter, read_recording
from tools.wiimote_bridge.service import BridgeService, newer

MAC = bytes.fromhex("001122334455")


def temporary_directory():
    # The Windows sandbox's redirected %TEMP% can create a directory but deny
    # files within it. Keep all test artifacts under the writable workspace.
    root = Path(__file__).resolve().parents[2] / "build" / "host-tests"
    root.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(dir=root)


def snapshot(*, sequence: int = 1, sample: int = 1, event: int = 0,
             flags: int = 7, age: int = 0, boot: int = 42, buttons: int = 0x100) -> Frame:
    return Frame(MessageKind.SNAPSHOT, boot, sequence, 100,
                 tuple(SnapshotSlot(i, flags if i == 0 else 0, buttons if i == 0 else 0,
                                    0, 0, 128 if i == 0 else 0, age, sample, event)
                       for i in range(4)))


def devices(*, sequence: int = 2, boot: int = 42, source: int = 0) -> Frame:
    return Frame(MessageKind.DEVICES, boot, sequence, 100,
                 tuple(DeviceRecord(i, int(i == source), MAC if i == source else bytes(6)) for i in range(4)))


def event(*, sequence: int = 3, number: int = 1, timestamp: int = 100,
          sender_ms: int = 100, boot: int = 42, source: int = 0) -> Frame:
    return Frame(MessageKind.EVENTS, boot, sequence, sender_ms,
                 (InputEvent(source, EventKind.BUTTONS, 0x101, number, 1, timestamp),))


class MappingTests(unittest.TestCase):
    def test_normalize_and_round_trip(self) -> None:
        self.assertEqual(normalize_mac(MAC), "00:11:22:33:44:55")
        with temporary_directory() as directory:
            target = Path(directory) / "config.json"
            registry = DeviceRegistry()
            registry.assign("00-11-22-33-44-55", 8)
            registry.save(target)
            self.assertEqual(DeviceRegistry.load(target).player_for(MAC), 8)

    def test_no_silent_reassignment(self) -> None:
        registry = DeviceRegistry({"00:11:22:33:44:55": 5})
        with self.assertRaises(MappingError):
            registry.assign(MAC, 6)
        with self.assertRaises(MappingError):
            registry.assign("11:22:33:44:55:66", 5)

    def test_invalid_players_addresses_and_duplicates(self) -> None:
        for address in (bytes(6), "FF:FF:FF:FF:FF:FF", "00:11:22", "hello"):
            with self.assertRaises(MappingError):
                DeviceRegistry().assign(address, 5)
        for player in (4, 9, True, "5"):
            with self.assertRaises(MappingError):
                DeviceRegistry().assign(MAC, player)
        with self.assertRaises(MappingError):
            DeviceRegistry({"001122334455": 5, "00:11:22:33:44:55": 6})

    def test_port_selection_never_falls_back_to_first(self) -> None:
        unknown = PortInfo("COM8", "Some USB device", 1, 2)
        known = PortInfo("COM9", "CP210x", 0x10C4, 0xEA60)
        self.assertEqual(choose_port([unknown, known]), known)
        self.assertEqual(choose_port([unknown], "com8"), unknown)
        for ports in ([unknown], [], [known, PortInfo("COM10", vid=0x1A86, pid=0x7523)]):
            with self.assertRaises(PortSelectionError):
                choose_port(ports)


class ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = BridgeService(DeviceRegistry({normalize_mac(MAC): 8}))
        self.service.ingest(devices(sequence=1), now_ms=0)
        self.service.ingest(snapshot(sequence=2), now_ms=0)

    def test_explicit_identity_routes_source_zero_to_p8(self) -> None:
        view = self.service.view(now_ms=0)
        self.assertEqual(view.players, (8,))
        self.assertEqual(view.slots[3].buttons, 0x100)
        self.assertEqual(view.slots[0].flags, 0)

    def test_repeated_snapshot_does_not_refresh_sensor(self) -> None:
        self.service.ingest(snapshot(sequence=3), now_ms=200)
        self.assertEqual(self.service.view(now_ms=249).players, (8,))
        self.assertEqual(self.service.view(now_ms=250).players, ())
        self.service.ingest(snapshot(sequence=4, sample=2), now_ms=260)
        self.assertEqual(self.service.view(now_ms=260).players, (8,))

    def test_bad_calibration_is_neutral(self) -> None:
        self.service.ingest(snapshot(sequence=3, flags=5, sample=2), now_ms=10)
        self.assertEqual(self.service.view(now_ms=10).players, ())

    def test_duplicates_never_retrigger_and_ack_waits_for_guest(self) -> None:
        self.service.ingest(event(sequence=3), now_ms=10)
        self.service.ingest(event(sequence=4), now_ms=11)
        self.assertEqual(len(self.service.view(now_ms=11).events), 1)
        self.assertEqual(self.service.ack_records()[0].acked_event_sequence, 0)
        self.service.acknowledge_guest([0, 0, 0, 5])
        self.assertEqual(len(self.service.view(now_ms=11).events), 1)
        self.service.acknowledge_guest([0, 0, 0, 1])
        self.assertEqual(self.service.view(now_ms=11).events, ())
        self.assertEqual(self.service.ack_records()[0].acked_event_sequence, 1)

    def test_event_gap_neutralizes_without_acknowledging_missing_events(self) -> None:
        self.service.ingest(event(number=2), now_ms=10)
        self.assertEqual(self.service.view(now_ms=10).players, ())
        self.assertIn("event sequence gap", self.service.view(now_ms=10).faults[0])
        self.assertEqual(self.service.ack_records()[0].acked_event_sequence, 0)

    def test_queue_overflow_neutralizes(self) -> None:
        self.service.max_events_per_slot = 1
        self.service.ingest(event(sequence=3), now_ms=10)
        self.service.ingest(event(sequence=4, number=2), now_ms=11)
        self.assertEqual(self.service.view(now_ms=11).players, ())
        self.assertEqual(self.service.counters["queue_overflows"], 1)

    def test_stale_event_neutralizes_instead_of_delayed_item(self) -> None:
        self.service.ingest(event(timestamp=0, sender_ms=300), now_ms=10)
        self.assertEqual(self.service.view(now_ms=10).events, ())
        self.assertEqual(self.service.view(now_ms=10).players, ())

    def test_guest_stall_does_not_replay_old_event_with_new_sensor_sample(self) -> None:
        self.service.ingest(event(sequence=3), now_ms=10)
        self.service.ingest(snapshot(sequence=4, sample=2), now_ms=270)
        self.assertEqual(self.service.view(now_ms=270).events, ())
        self.assertEqual(self.service.view(now_ms=270).players, ())
        self.assertIn("consumption stalled", self.service.view(now_ms=270).faults[0])

    def test_disconnect_discards_pending_and_reconnect_uses_baseline(self) -> None:
        self.service.ingest(event(sequence=3), now_ms=10)
        self.service.ingest(snapshot(sequence=4, flags=0, event=3), now_ms=20)
        self.assertEqual(self.service.view(now_ms=20).events, ())
        self.assertEqual(self.service.ack_records()[0].acked_event_sequence, 3)
        self.service.ingest(snapshot(sequence=5, sample=2, event=3), now_ms=30)
        self.service.ingest(event(sequence=6, number=4), now_ms=40)
        self.assertEqual(self.service.view(now_ms=40).events[0].event_sequence, 4)

    def test_firmware_overflow_is_neutral_and_acknowledged_before_release_recovery(self) -> None:
        self.service.ingest(snapshot(sequence=3, flags=15, sample=2, event=4), now_ms=10)
        self.assertEqual(self.service.view(now_ms=10).players, ())
        self.assertEqual(self.service.ack_records()[0].acked_event_sequence, 4)
        self.service.ingest(snapshot(sequence=4, flags=7, sample=3, event=4), now_ms=20)
        self.assertEqual(self.service.view(now_ms=20).players, ())
        self.service.ingest(snapshot(sequence=5, flags=7, sample=4, event=5, buttons=0), now_ms=30)
        self.assertEqual(self.service.view(now_ms=30).players, (8,))
        self.assertEqual(self.service.ack_records()[0].acked_event_sequence, 5)

    def test_boot_change_clears_devices_states_and_old_boot_is_rejected(self) -> None:
        self.service.ingest(snapshot(sequence=1, boot=99), now_ms=10)
        self.assertEqual(self.service.view(now_ms=10).players, ())
        self.assertFalse(self.service.ingest(devices(sequence=100, boot=42), now_ms=20))
        self.assertEqual(self.service.boot_session, 99)

    def test_transport_and_sensor_sequence_wrap(self) -> None:
        self.assertTrue(newer(0, 0xFFFFFFFF))
        self.assertFalse(newer(0xFFFFFFFF, 0))
        self.assertFalse(newer(5, 5))

    def test_diagnostic_sink_explicitly_consumes_events_without_game(self) -> None:
        self.service.ingest(event(sequence=3), now_ms=10)
        self.service.drain_diagnostic_events()
        self.assertEqual(self.service.ack_records()[0].acked_event_sequence, 1)


class RecordingTests(unittest.TestCase):
    def test_round_trip_and_existing_file_refused(self) -> None:
        with temporary_directory() as directory:
            target = Path(directory) / "capture.jsonl"
            with RecordingWriter(target, started_ns=100) as writer:
                writer.append(b"W3", now_ns=110)
                writer.append(b"\x00\xff", now_ns=120)
            records = list(read_recording(target))
            self.assertEqual([(r.elapsed_ns, r.data) for r in records], [(10, b"W3"), (20, b"\x00\xff")])
            with self.assertRaises(FileExistsError):
                RecordingWriter(target)

    def test_backwards_or_oversized_records_are_refused(self) -> None:
        with temporary_directory() as directory:
            target = Path(directory) / "capture.jsonl"
            with RecordingWriter(target, started_ns=100) as writer:
                writer.append(b"a", now_ns=110)
                with self.assertRaises(RecordingError):
                    writer.append(b"b", now_ns=109)
            target.write_text(json.dumps({"format": "ss8-wiimote-serial", "version": 1}) + "\n"
                              + json.dumps({"elapsed_ns": 0, "data_hex": "ff" * 4097}) + "\n", encoding="utf-8")
            with self.assertRaises(RecordingError):
                list(read_recording(target))

    def test_cli_help_needs_no_optional_packages(self) -> None:
        completed = subprocess.run([sys.executable, "-S", "-m", "tools.wiimote_bridge", "--help"],
                                   capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--diagnose", completed.stdout)

    def test_cli_replay_is_offline_and_needs_no_optional_packages(self) -> None:
        with temporary_directory() as directory:
            capture = Path(directory) / "capture.jsonl"
            config = Path(directory) / "config.json"
            DeviceRegistry({normalize_mac(MAC): 5}).save(config)
            with RecordingWriter(capture, started_ns=0) as writer:
                writer.append(encode_frame(devices(sequence=1)), now_ns=0)
                writer.append(encode_frame(snapshot(sequence=2)), now_ns=1_000_000)
            completed = subprocess.run([sys.executable, "-S", "-m", "tools.wiimote_bridge", "--replay",
                                        str(capture), "--config", str(config)],
                                       capture_output=True, text=True, check=False)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            summary = json.loads(completed.stdout.splitlines()[0])
            self.assertEqual(summary["players_fresh"], [5])
            self.assertEqual(summary["sources"][0]["accel"], [0, 0, 128])
            self.assertIn("no serial port or Dolphin process", completed.stdout)


if __name__ == "__main__":
    unittest.main()
