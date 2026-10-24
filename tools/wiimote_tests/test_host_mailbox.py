"""Independent byte-layout fixtures and rejected-write tests for guest ABI v1."""
from __future__ import annotations

import struct
import unittest
import zlib

from tools.wiimote_bridge.mailbox import (BuildManifest, Descriptor, GuestMailbox, GuestStatus,
                                         MailboxBusyError, MailboxError, encode_input)
from tools.wiimote_bridge.service import HostView, neutral_slot
from tools.wiimote_bridge.windows_memory import WindowsProcessMemory

DESCRIPTOR = 0x80010000
INPUT = 0x80011000
STATUS = 0x80012000
BUILD = bytes(range(16))


def descriptor(*, build: bytes = BUILD, guest_session: int = 22, input_address: int = INPUT,
               status_address: int = STATUS) -> bytes:
    result = bytearray(64)
    struct.pack_into(">8sHHI16sIIIIIHHI", result, 0, b"SS8WBRG1", 1, 64, 1, build,
                     guest_session, input_address, 640, status_address, 96, 4, 0, 1)
    struct.pack_into(">I", result, 60, zlib.crc32(result[:60]))
    return bytes(result)


def status(*, generation: int = 2, host_session: int = 33, guest_session: int = 22) -> bytes:
    result = bytearray(96)
    struct.pack_into(">8I", result, 0, generation, guest_session, 50, host_session, 6, 42, 3, 0)
    struct.pack_into(">4I", result, 32, 1, 2, 3, 4)
    struct.pack_into(">4I", result, 48, 5, 6, 7, 8)
    struct.pack_into(">4I", result, 64, 0, 1, 2, 3)
    struct.pack_into(">I", result, 92, zlib.crc32(result[4:92]))
    return bytes(result)


class FakeMemory:
    pid = 1234

    def __init__(self) -> None:
        self.regions = {0x80000000: b"RMCP01", DESCRIPTOR: descriptor(), STATUS: status()}
        self.writes: list[tuple[int, bytes]] = []
        self.alive = True
        self.authorized = None

    def ensure_target(self) -> None:
        if not self.alive:
            raise MailboxError("Selected process exited")

    def read(self, address: int, size: int) -> bytes:
        for base, data in self.regions.items():
            if base <= address and address + size <= base + len(data):
                return data[address - base:address - base + size]
        raise MailboxError("Unknown memory read")

    def authorize_write_range(self, address: int, size: int) -> None:
        self.authorized = (address, size)

    def write(self, address: int, data: bytes) -> None:
        self.writes.append((address, data))


class MailboxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.memory = FakeMemory()
        self.manifest = BuildManifest(BUILD, "RMCP01")
        self.view = HostView(42, tuple(neutral_slot(i) for i in range(4)), (), (), ())

    def test_validated_descriptor_authorizes_only_input_range(self) -> None:
        GuestMailbox(self.memory, DESCRIPTOR, self.manifest, host_session=33)
        self.assertEqual(self.memory.authorized, (INPUT, 640))

    def test_wrong_game_or_build_or_process_means_no_writes(self) -> None:
        for fault in ("game", "build", "process"):
            with self.subTest(fault=fault):
                memory = FakeMemory()
                if fault == "game":
                    memory.regions[0x80000000] = b"RMCE01"
                elif fault == "build":
                    memory.regions[DESCRIPTOR] = descriptor(build=bytes(16))
                else:
                    memory.alive = False
                with self.assertRaises(MailboxError):
                    GuestMailbox(memory, DESCRIPTOR, self.manifest)
                self.assertEqual(memory.writes, [])
                self.assertIsNone(memory.authorized)

    def test_overlapping_or_outside_buffers_rejected(self) -> None:
        for input_address, status_address in ((DESCRIPTOR, STATUS), (INPUT, INPUT),
                                              (0x817FFFF0, STATUS), (0x1234, STATUS)):
            with self.assertRaises(MailboxError):
                Descriptor.decode(descriptor(input_address=input_address, status_address=status_address), BUILD, DESCRIPTOR)

    def test_input_layout_and_crc(self) -> None:
        data = encode_input(self.view, generation=2, guest_session=22,
                            host_session=33, publish_sequence=1, host_elapsed_ms=123)
        self.assertEqual(len(data), 640)
        self.assertEqual(struct.unpack_from(">6IHH", data), (2, 22, 33, 1, 42, 123, 0, 4))
        self.assertEqual(struct.unpack_from(">I", data, 28)[0], zlib.crc32(data[4:28] + data[32:]))
        self.assertEqual(data[32], 0)
        self.assertEqual(data[56], 1)
        self.assertEqual(data[80], 2)
        self.assertEqual(data[104], 3)
        self.assertEqual(data[128:], bytes(512))

    def test_commit_is_odd_payload_even(self) -> None:
        mailbox = GuestMailbox(self.memory, DESCRIPTOR, self.manifest, host_session=33)
        mailbox.publish(self.view, host_elapsed_ms=100)
        writes = self.memory.writes
        self.assertEqual(len(writes), 3)
        self.assertEqual(writes[0], (INPUT, struct.pack(">I", 3)))
        self.assertEqual(writes[1][0], INPUT + 4)
        self.assertEqual(len(writes[1][1]), 636)
        self.assertEqual(writes[2], (INPUT, struct.pack(">I", 2)))

    def test_guest_restart_prevents_writes_to_old_buffers(self) -> None:
        mailbox = GuestMailbox(self.memory, DESCRIPTOR, self.manifest, host_session=33)
        self.memory.regions[DESCRIPTOR] = descriptor(guest_session=23)
        with self.assertRaises(MailboxError):
            mailbox.publish(self.view, host_elapsed_ms=100)
        self.assertEqual(self.memory.writes, [])

    def test_status_layout_and_torn_crc(self) -> None:
        value = GuestStatus.decode(status(), guest_session=22)
        self.assertEqual(value.acknowledged_events, (1, 2, 3, 4))
        self.assertEqual(value.applied_samples, (5, 6, 7, 8))
        self.assertEqual(value.host_session, 33)
        torn = bytearray(status())
        torn[40] ^= 1
        with self.assertRaises(MailboxError):
            GuestStatus.decode(bytes(torn), guest_session=22)

    def test_status_busy_is_bounded_and_does_not_write(self) -> None:
        mailbox = GuestMailbox(self.memory, DESCRIPTOR, self.manifest, host_session=33)
        self.memory.regions[STATUS] = status(generation=3)
        with self.assertRaises(MailboxBusyError):
            mailbox.read_status()
        self.assertEqual(self.memory.writes, [])

    def test_explicit_host_ram_translation_is_bounded(self) -> None:
        # Exercise only address translation, without opening a real process.
        backend = WindowsProcessMemory.__new__(WindowsProcessMemory)
        backend.mem1_base = 0x1234000000
        backend.mem2_base = None
        self.assertEqual(backend._host_address(0x80000100, 8), 0x1234000100)
        for address, size in ((0x7FFFFFFC, 4), (0x817FFFFC, 8), (0x90000000, 4), (0x94000000, 4)):
            with self.assertRaises(MailboxError):
                backend._host_address(address, size)
        backend.mem2_base = 0x5678000000
        self.assertEqual(backend._host_address(0x90000100, 8), 0x5678000100)

    def test_live_backend_refuses_any_write_before_authorization(self) -> None:
        backend = WindowsProcessMemory.__new__(WindowsProcessMemory)
        backend.write_range = None
        backend.ensure_target = lambda: None
        with self.assertRaises(MailboxError):
            backend.write(INPUT, b"test")
        backend.write_range = (INPUT, INPUT + 640)
        for address, data in ((INPUT - 4, bytes(4)), (INPUT + 638, bytes(4)), (STATUS, bytes(4))):
            with self.assertRaises(MailboxError):
                backend.write(address, data)


if __name__ == "__main__":
    unittest.main()
