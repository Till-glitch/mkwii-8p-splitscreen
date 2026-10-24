"""Run the real CodeWarrior-compiled guest receiver in Unicorn PPC32.

Use tools/.venv/Scripts/python.exe -m unittest discover -s tools/wiimote_tests
or select this file with -p test_guest_mailbox_ppc.py. Input/status bytes are
independently assembled with struct/zlib, not the production Python codec.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
import struct
import subprocess
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[2]
COMPILER = ROOT / "tools/cw-wii17/mwcceppc.exe"
LINKER = ROOT / "tools/kamek/Kamek.exe"
HARNESS = Path(__file__).with_name("guest_mailbox_harness.cpp")
OUTPUT = ROOT / "build/wiimote-tests"
CODE = 0x80010000
STOP = CODE + 0xFFF0
DATA = 0x90000000
INPUT = DATA + 0x1000
STATUS = DATA + 0x2000
SLOT_OUTPUT = DATA + 0x3000
STACK = 0x90100000
GUEST = 0x12345678
HOST = 0x23456789
SOURCE = 0x3456789A
SNAPSHOT = struct.Struct(">BBHhhhHIIHH")
EVENT = struct.Struct(">BBHIII")
TIMEOUT_MS = 250
READY, APPLIED, TIMEOUT, PROTOCOL_ERROR = 1, 2, 4, 8
ERROR_SESSION, ERROR_CRC, ERROR_SHAPE, ERROR_SEQUENCE, ERROR_EVENT = range(1, 6)

try:
    import unicorn
    from unicorn import ppc_const as PPC
except ImportError:
    unicorn = None
    PPC = None


def build_harness() -> tuple[bytes, dict[str, int]]:
    if unicorn is None:
        raise unittest.SkipTest("Unicorn is unavailable; install the project's tools/.venv dependencies")
    for tool in (COMPILER, LINKER):
        if not tool.is_file():
            raise unittest.SkipTest(f"required target tool is unavailable: {tool}")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    obj = OUTPUT / "guest.o"
    binary = OUTPUT / "guest.bin"
    mapping = OUTPUT / "guest.map"
    stamp = OUTPUT / "guest-build.sha256"
    fingerprint = hashlib.sha256()
    for path in (HARNESS, ROOT / "shared/wheel_bridge_mailbox.h", ROOT / "shared/wii_bridge_protocol.h"):
        fingerprint.update(path.read_bytes())
    for tool in (COMPILER, LINKER):
        fingerprint.update(f"{tool}:{tool.stat().st_size}:{tool.stat().st_mtime_ns}".encode())
    flags = ["-I-", "-i", str(ROOT / "shared"), "-proc", "gekko", "-fp", "hard", "-sdata", "0", "-sdata2", "0", "-opt", "all", "-inline", "auto", "-enum", "int", "-use_lmw_stmw", "on"]
    fingerprint.update(repr(flags).encode())
    digest = fingerprint.hexdigest()
    if not (binary.is_file() and mapping.is_file() and stamp.is_file() and stamp.read_text().strip() == digest):
        compile_result = subprocess.run([str(COMPILER), *flags, "-c", str(HARNESS), "-o", str(obj)], cwd=ROOT, capture_output=True, text=True, timeout=60)
        if compile_result.returncode:
            raise AssertionError("CodeWarrior guest harness build failed:\n" + compile_result.stdout + compile_result.stderr)
        # For static Kamek links, output-code is the raw linked binary.
        link_result = subprocess.run([str(LINKER), str(obj), f"-static=0x{CODE:08x}", f"-output-code={binary}", f"-output-map={mapping}"], cwd=ROOT, capture_output=True, text=True, timeout=60)
        if link_result.returncode:
            raise AssertionError("Kamek guest harness link failed:\n" + link_result.stdout + link_result.stderr)
        stamp.write_text(digest + "\n", encoding="ascii")
    symbols = {}
    for line in mapping.read_text(encoding="utf-8").splitlines():
        columns = line.split()
        if len(columns) == 3 and re.fullmatch(r"[0-9A-Fa-f]{8}", columns[0]):
            symbols[columns[2]] = int(columns[0], 16)
    required = {"ss8_receiver_size", "ss8_reset", "ss8_accept", "ss8_tick", "ss8_status", "ss8_read_slot"}
    if missing := required - symbols.keys():
        raise AssertionError(f"missing harness exports: {sorted(missing)}")
    code = binary.read_bytes()
    if len(code) >= STOP - CODE:
        raise AssertionError("guest harness outgrew its emulated code area")
    return code, symbols


def slot(slot_id: int, *, flags: int = 7, buttons: int = 0x100,
         sequence: int = 1, age_ms: int = 0, last_event: int = 0,
         reserved: int = 0) -> bytes:
    return SNAPSHOT.pack(slot_id, flags, buttons, -128, 0, 128, age_ms, sequence, last_event, 0, reserved)


def event(slot_id: int, sequence: int, *, kind: int = 1, value: int = 0x100,
          sample_sequence: int = 1, time_ms: int = 100) -> bytes:
    return EVENT.pack(slot_id, kind, value, sequence, sample_sequence, time_ms)


def input_bytes(*, guest: int = GUEST, host: int = HOST, source: int = SOURCE,
                publish: int = 1, slots: list[bytes] | None = None,
                events: tuple[bytes, ...] = (), slot_count: int = 4,
                generation: int = 2) -> bytes:
    data = bytearray(640)
    struct.pack_into(">IIIIIIHHI", data, 0, generation, guest, host, publish, source, 100, len(events), slot_count, 0)
    data[32:128] = b"".join(slots if slots is not None else [slot(i) for i in range(4)])
    data[128:128 + len(events) * EVENT.size] = b"".join(events)
    return with_input_crc(data)


def with_input_crc(data: bytes | bytearray) -> bytes:
    result = bytearray(data)
    if len(result) != 640:
        raise ValueError("test input must be exactly 640 bytes")
    struct.pack_into(">I", result, 28, zlib.crc32(result[4:28] + result[32:]) & 0xFFFFFFFF)
    return bytes(result)


class GuestMailboxPpcTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.code, cls.symbols = build_harness()

    def setUp(self):
        self.uc = unicorn.Uc(unicorn.UC_ARCH_PPC, unicorn.UC_MODE_PPC32 | unicorn.UC_MODE_BIG_ENDIAN)
        self.uc.mem_map(CODE, 0x10000)
        self.uc.mem_map(DATA, 0x10000)
        self.uc.mem_map(STACK, 0x10000)
        self.uc.mem_write(CODE, self.code)
        self.assertLess(self.invoke("ss8_receiver_size"), INPUT - DATA)
        self.invoke("ss8_reset", DATA, GUEST)

    def invoke(self, name: str, *arguments: int) -> int:
        self.uc.reg_write(PPC.UC_PPC_REG_1, STACK + 0xF000)
        self.uc.reg_write(PPC.UC_PPC_REG_LR, STOP)
        for index, value in enumerate(arguments, 3):
            self.uc.reg_write(getattr(PPC, f"UC_PPC_REG_{index}"), value & 0xFFFFFFFF)
        try:
            self.uc.emu_start(self.symbols[name], STOP, count=1_000_000)
        except unicorn.UcError as error:
            pc = self.uc.reg_read(PPC.UC_PPC_REG_PC)
            self.fail(f"PPC harness {name} failed at 0x{pc:08x}: {error}")
        self.assertEqual(self.uc.reg_read(PPC.UC_PPC_REG_PC), STOP, "instruction budget exhausted")
        return self.uc.reg_read(PPC.UC_PPC_REG_3) & 0xFFFFFFFF

    def accept(self, data: bytes, now: int = 100) -> bool:
        self.assertEqual(len(data), 640)
        self.uc.mem_write(INPUT, bytes(data))
        return bool(self.invoke("ss8_accept", DATA, INPUT, now))

    def tick(self, now: int):
        self.invoke("ss8_tick", DATA, now)

    def status(self) -> dict:
        self.invoke("ss8_status", DATA, STATUS, 8)
        raw = bytes(self.uc.mem_read(STATUS, 96))
        words = struct.unpack(">24I", raw)
        self.assertEqual(words[0], 8)
        self.assertEqual(words[23], zlib.crc32(raw[4:92]) & 0xFFFFFFFF)
        self.assertEqual(words[20:23], (0, 0, 0))
        return dict(guest=words[1], tick=words[2], host=words[3], publish=words[4], source=words[5], flags=words[6], error=words[7], event_ack=words[8:12], sample_sequence=words[12:16], bound_mask=words[16], age_ticks=words[17], accepted=words[18], rejected=words[19])

    def read_slot(self, index: int) -> tuple:
        self.assertEqual(self.invoke("ss8_read_slot", DATA, index, SLOT_OUTPUT), 24)
        return SNAPSHOT.unpack(bytes(self.uc.mem_read(SLOT_OUTPUT, 24)))

    def assert_error(self, error: int, accepted: int = 0):
        status = self.status()
        self.assertEqual(status["error"], error)
        self.assertTrue(status["flags"] & PROTOCOL_ERROR)
        self.assertEqual(status["accepted"], accepted)
        self.assertGreater(status["rejected"], 0)

    def test_reset_status_crc_and_no_gameplay_binding(self):
        status = self.status()
        self.assertEqual((status["guest"], status["host"], status["source"]), (GUEST, 0, 0))
        self.assertEqual(status["flags"], READY)
        self.assertEqual(status["event_ack"], (0, 0, 0, 0))
        self.assertEqual(status["bound_mask"], 0)
        for index in range(4):
            actual = self.read_slot(index)
            self.assertEqual(actual[:6], (index, 0, 0, 0, 0, 0))

    def test_valid_snapshot_updates_only_diagnostic_state(self):
        self.assertTrue(self.accept(input_bytes()))
        self.tick(100)
        status = self.status()
        self.assertEqual((status["host"], status["source"], status["publish"]), (HOST, SOURCE, 1))
        self.assertEqual((status["accepted"], status["rejected"]), (1, 0))
        self.assertEqual(status["flags"], READY | APPLIED)
        self.assertEqual(status["bound_mask"], 0)
        self.assertEqual(status["sample_sequence"], (1, 1, 1, 1))
        self.assertEqual(self.read_slot(0)[1:6], (7, 0x100, -128, 0, 128))

    def test_bad_crc_changes_no_accepted_state(self):
        self.assertTrue(self.accept(input_bytes()))
        before = self.read_slot(0)
        damaged = bytearray(input_bytes(publish=2, slots=[slot(i, buttons=0x400) for i in range(4)]))
        damaged[35] ^= 1
        self.assertFalse(self.accept(damaged, 110))
        self.assert_error(ERROR_CRC, accepted=1)
        self.assertEqual(self.read_slot(0), before)
        self.assertEqual(self.status()["publish"], 1)

    def test_wrong_or_zero_sessions_rejected(self):
        for kwargs in ({"guest": GUEST + 1}, {"host": 0}, {"source": 0}):
            with self.subTest(kwargs=kwargs):
                self.assertFalse(self.accept(input_bytes(**kwargs)))
                self.assert_error(ERROR_SESSION)

    def test_slot_count_and_count_limit_rejected(self):
        self.assertFalse(self.accept(input_bytes(slot_count=3)))
        self.assert_error(ERROR_SHAPE)
        invalid = bytearray(input_bytes())
        struct.pack_into(">H", invalid, 24, 33)
        self.assertFalse(self.accept(with_input_crc(invalid)))
        self.assert_error(ERROR_SHAPE)

    def test_uncommitted_input_generation_rejected(self):
        for generation in (0, 1, 3, 0xFFFFFFFF):
            with self.subTest(generation=generation):
                self.assertFalse(self.accept(input_bytes(generation=generation)))
                self.assert_error(ERROR_SHAPE)
    def test_unknown_flags_bad_axis_reserved_and_padding_rejected(self):
        for offset, fmt, value in ((33, ">B", 0x80), (36, ">h", 512), (54, ">H", 1), (639, ">B", 1)):
            damaged = bytearray(input_bytes())
            struct.pack_into(fmt, damaged, offset, value)
            with self.subTest(offset=offset):
                self.assertFalse(self.accept(with_input_crc(damaged)))
                self.assert_error(ERROR_SHAPE)

    def test_duplicate_and_unordered_slots_rejected(self):
        for slots in ([slot(0), slot(1), slot(2), slot(0)], [slot(1), slot(0), slot(2), slot(3)]):
            self.assertFalse(self.accept(input_bytes(slots=slots)))
            self.assert_error(ERROR_SHAPE)

    def test_duplicate_and_old_publishes_rejected_without_refresh(self):
        self.assertTrue(self.accept(input_bytes(publish=8), now=100))
        for publish in (8, 7):
            self.assertFalse(self.accept(input_bytes(publish=publish), now=300))
            self.assert_error(ERROR_SEQUENCE, accepted=1)
        self.tick(350)
        self.assertTrue(self.status()["flags"] & TIMEOUT)
        self.assertEqual(self.read_slot(0)[2], 0)

    def test_publish_and_sample_sequence_wrap(self):
        self.assertTrue(self.accept(input_bytes(publish=0xFFFFFFFF, slots=[slot(i, sequence=0xFFFFFFFF) for i in range(4)])))
        self.assertTrue(self.accept(input_bytes(publish=0, slots=[slot(i, sequence=0) for i in range(4)]), 110))
        self.assertEqual(self.status()["sample_sequence"], (0, 0, 0, 0))
        self.assertFalse(self.accept(input_bytes(publish=0x80000000), 120))
        self.assert_error(ERROR_SEQUENCE, accepted=2)

    def test_older_sample_rejected_transactionally(self):
        self.assertTrue(self.accept(input_bytes(slots=[slot(i, sequence=3) for i in range(4)])))
        slots = [slot(i, sequence=4, buttons=0x400) for i in range(4)]
        slots[3] = slot(3, sequence=2)
        self.assertFalse(self.accept(input_bytes(publish=2, slots=slots, events=(event(0, 10),)), 110))
        self.assert_error(ERROR_SEQUENCE, accepted=1)
        self.assertEqual(self.read_slot(0)[2], 0x100)
        self.assertEqual(self.status()["event_ack"], (0, 0, 0, 0))

    def test_event_order_duplicates_wrap_and_cumulative_ack(self):
        self.assertTrue(self.accept(input_bytes(events=(event(0, 0xFFFFFFFF), event(0, 0), event(0, 1), event(2, 20)))))
        self.assertEqual(self.status()["event_ack"], (1, 0, 20, 0))
        self.assertTrue(self.accept(input_bytes(publish=2, events=(event(0, 1), event(0, 0), event(0, 2))), 110))
        self.assertEqual(self.status()["event_ack"], (2, 0, 20, 0))
        self.assertEqual(self.status()["bound_mask"], 0)

    def test_event_gap_and_invalid_kind_rejected_transactionally(self):
        self.assertTrue(self.accept(input_bytes(events=(event(0, 10),))))
        self.assertFalse(self.accept(input_bytes(publish=2, events=(event(1, 30), event(0, 12))), 110))
        self.assert_error(ERROR_EVENT, accepted=1)
        self.assertEqual(self.status()["event_ack"], (10, 0, 0, 0))
        self.assertFalse(self.accept(input_bytes(publish=2, events=(event(0, 11, kind=3),)), 110))
        self.assert_error(ERROR_EVENT, accepted=1)

    def test_new_host_or_source_resets_sequence_domains(self):
        self.assertTrue(self.accept(input_bytes(publish=50, slots=[slot(i, sequence=20) for i in range(4)], events=(event(0, 30),))))
        self.assertTrue(self.accept(input_bytes(host=HOST + 1, publish=1, slots=[slot(i, sequence=1) for i in range(4)], events=(event(0, 2),)), 110))
        self.assertEqual(self.status()["event_ack"], (2, 0, 0, 0))
        self.assertTrue(self.accept(input_bytes(host=HOST + 1, source=SOURCE + 1, publish=1, events=(event(0, 1),)), 120))
        self.assertEqual(self.status()["event_ack"], (1, 0, 0, 0))
        self.assertEqual(self.status()["source"], SOURCE + 1)

    def test_host_timeout_boundary(self):
        self.assertTrue(self.accept(input_bytes(), 100))
        self.tick(349)
        self.assertEqual(self.read_slot(0)[2], 0x100)
        self.tick(350)
        self.assertEqual(self.read_slot(0)[1:6], (0, 0, 0, 0, 0))
        self.assertTrue(self.status()["flags"] & TIMEOUT)

    def test_fresh_publishes_do_not_refresh_same_radio_sample(self):
        for publish, now in ((1, 100), (2, 200), (3, 300), (4, 350)):
            self.assertTrue(self.accept(input_bytes(publish=publish), now))
            self.tick(now)
        self.assertEqual(self.read_slot(0)[2], 0)
        self.assertTrue(self.status()["flags"] & TIMEOUT)

    def test_only_stale_slot_neutralized_other_slots_remain_independent(self):
        for publish, now in ((1, 100), (2, 200), (3, 300), (4, 350)):
            slots = [slot(0, sequence=1)] + [slot(i, sequence=publish, buttons=0x100 + i) for i in range(1, 4)]
            self.assertTrue(self.accept(input_bytes(publish=publish, slots=slots), now))
            self.tick(now)
        self.assertEqual(self.read_slot(0)[2], 0)
        for index in range(1, 4):
            self.assertEqual(self.read_slot(index)[2], 0x100 + index)
        self.assertEqual(self.status()["sample_sequence"], (1, 4, 4, 4))

    def test_reported_sensor_age_causes_immediate_neutral(self):
        slots = [slot(0, age_ms=TIMEOUT_MS)] + [slot(i) for i in range(1, 4)]
        self.assertTrue(self.accept(input_bytes(slots=slots), 100))
        self.tick(100)
        self.assertEqual(self.read_slot(0)[2], 0)
        self.assertEqual(self.read_slot(1)[2], 0x100)

    def test_disconnect_and_overflow_neutralize_and_ack_drop_boundary(self):
        slots = [slot(0, flags=0, last_event=100), slot(1, flags=15, last_event=200), slot(2), slot(3)]
        self.assertTrue(self.accept(input_bytes(slots=slots)))
        self.tick(100)
        self.assertEqual(self.read_slot(0)[1:6], (0, 0, 0, 0, 0))
        self.assertEqual(self.read_slot(1)[1:6], (0, 0, 0, 0, 0))
        self.assertEqual(self.status()["event_ack"], (100, 200, 0, 0))
        self.assertEqual(self.read_slot(2)[2], 0x100)

    def test_monotonic_millisecond_wrap(self):
        self.assertTrue(self.accept(input_bytes(), 0xFFFFFFF0))
        self.tick(0x00000020)
        self.assertEqual(self.read_slot(0)[2], 0x100)
        self.tick(0x000000EA)
        self.assertEqual(self.read_slot(0)[2], 0)
        self.assertTrue(self.status()["flags"] & TIMEOUT)

    def test_reset_active_receiver_clears_prior_sessions_and_ack(self):
        self.assertTrue(self.accept(input_bytes(events=(event(0, 30),))))
        self.tick(100)
        self.invoke("ss8_reset", DATA, GUEST + 1)
        status = self.status()
        self.assertEqual((status["guest"], status["host"], status["source"]), (GUEST + 1, 0, 0))
        self.assertEqual((status["accepted"], status["rejected"], status["tick"]), (0, 0, 0))
        self.assertEqual(status["event_ack"], (0, 0, 0, 0))
        self.assertEqual(self.read_slot(0)[2], 0)
        self.assertFalse(self.accept(input_bytes(publish=2), 110))
        self.assert_error(ERROR_SESSION)
        self.assertTrue(self.accept(input_bytes(guest=GUEST + 1, publish=1), 120))

    def test_valid_publish_clears_previous_protocol_error(self):
        self.assertFalse(self.accept(input_bytes(host=0)))
        self.assert_error(ERROR_SESSION)
        self.assertTrue(self.accept(input_bytes()))
        status = self.status()
        self.assertEqual(status["flags"], READY | APPLIED)
        self.assertEqual(status["error"], 0)
        self.assertEqual((status["accepted"], status["rejected"]), (1, 1))

    def test_duplicate_report_cannot_reduce_reported_sample_age(self):
        self.assertTrue(self.accept(input_bytes(slots=[slot(i, age_ms=100) for i in range(4)]), 100))
        self.assertTrue(self.accept(input_bytes(publish=2), 200))
        self.tick(249)
        self.assertEqual(self.read_slot(0)[2], 0x100)
        self.tick(250)
        self.assertEqual(self.read_slot(0)[2], 0)

    def test_new_sensor_report_recovers_from_prior_timeout(self):
        self.assertTrue(self.accept(input_bytes(), 100))
        self.tick(350)
        self.assertEqual(self.read_slot(0)[2], 0)
        self.assertTrue(self.accept(input_bytes(publish=2, slots=[slot(i, sequence=2) for i in range(4)]), 351))
        self.tick(351)
        self.assertEqual(self.read_slot(0)[2], 0x100)
        self.assertEqual(self.status()["flags"], READY | APPLIED)


if __name__ == "__main__":
    unittest.main()
