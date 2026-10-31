"""Execute the portable firmware allocation helper as actual compiled PPC code.

No serial port, Nintendo resources or firmware upload is used. Run with the
project Python environment and local CodeWarrior/Kamek test toolchain.
"""
from __future__ import annotations

import hashlib
import itertools
from pathlib import Path
import re
import subprocess
import unittest

try:
    import unicorn
    from unicorn import ppc_const as PPC
except ImportError:
    unicorn = PPC = None

ROOT = Path(__file__).resolve().parents[3]
CODE, STOP, TABLE, ACTIVE, REMOTE, SAVED, STACK = (
    0x81700000, 0x8170FFF0, 0x90010000, 0x90010100,
    0x90010200, 0x90010300, 0x901F0000,
)
KNOWN = [bytes((0x10, 0x20, 0x30, 0x40, 0x50, i + 1)) for i in range(4)]
OTHER = bytes.fromhex("102030405099")


class SlotReservationsPpcTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if unicorn is None:
            raise unittest.SkipTest("install project test dependencies for Unicorn")
        compiler = ROOT / "tools/cw-wii17/mwcceppc.exe"
        linker = ROOT / "tools/kamek/Kamek.exe"
        for tool in (compiler, linker):
            if not tool.is_file():
                raise unittest.SkipTest(f"PPC test compiler unavailable: {tool}")
        source = Path(__file__).with_name("slot_reservations_harness.cpp")
        header = source.parent.parent / "include/wii_slot_reservations.h"
        output = ROOT / "build/wiimote-tests/firmware-slot-reservations"
        output.mkdir(parents=True, exist_ok=True)
        obj, binary, mapping, stamp = [output / name for name in (
            "slots.o", "slots.bin", "slots.map", "build.sha256")]
        flags = ["-I-", "-i", str(header.parent), "-proc", "gekko", "-sdata", "0", "-sdata2", "0", "-opt", "all", "-inline", "auto"]
        digest = hashlib.sha256(source.read_bytes() + header.read_bytes() + repr(flags).encode()).hexdigest()
        if not (binary.exists() and mapping.exists() and stamp.exists() and stamp.read_text().strip() == digest):
            for command in (
                [str(compiler), *flags, "-c", str(source), "-o", str(obj)],
                [str(linker), str(obj), f"-static=0x{CODE:08x}",
                 f"-output-code={binary}", f"-output-map={mapping}"],
            ):
                result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=60)
                if result.returncode:
                    raise AssertionError("slot reservation harness failed:\n" + result.stdout + result.stderr)
            stamp.write_text(digest + "\n", encoding="ascii")
        cls.code = binary.read_bytes()
        cls.exports = {}
        for line in mapping.read_text().splitlines():
            fields = line.split()
            if len(fields) == 3 and re.fullmatch(r"[0-9A-Fa-f]{8}", fields[0]):
                cls.exports[fields[2]] = int(fields[0], 16)

    def setUp(self):
        self.uc = unicorn.Uc(unicorn.UC_ARCH_PPC, unicorn.UC_MODE_PPC32 | unicorn.UC_MODE_BIG_ENDIAN)
        self.uc.mem_map(CODE, 0x10000)
        self.uc.mem_map(0x90000000, 0x200000)
        self.uc.mem_write(CODE, self.code)

    def invoke(self, name, *arguments):
        self.uc.reg_write(PPC.UC_PPC_REG_1, STACK)
        self.uc.reg_write(PPC.UC_PPC_REG_LR, STOP)
        for index, value in enumerate(arguments, 3):
            self.uc.reg_write(getattr(PPC, f"UC_PPC_REG_{index}"), value)
        self.uc.emu_start(self.exports[name], STOP, count=10000)
        self.assertEqual(self.uc.reg_read(PPC.UC_PPC_REG_PC), STOP)
        result = self.uc.reg_read(PPC.UC_PPC_REG_3) & 0xFFFFFFFF
        return result - 0x100000000 if result & 0x80000000 else result

    def select(self, addresses, active, remote=OTHER, pairing=True):
        self.uc.mem_write(TABLE, b"".join(addresses))
        self.uc.mem_write(ACTIVE, bytes(active))
        self.uc.mem_write(REMOTE, remote)
        return self.invoke("ss8_select", TABLE, ACTIVE, REMOTE, int(pairing))

    def test_known_remotes_reconnect_to_their_reservation_without_pairing(self):
        for active in itertools.product((False, True), repeat=4):
            for index in range(4):
                for pairing in (False, True):
                    expected = -1 if active[index] else index
                    self.assertEqual(self.select(KNOWN, active, KNOWN[index], pairing), expected)

    def test_unknown_remote_never_replaces_an_active_player(self):
        for active in itertools.product((False, True), repeat=4):
            expected = next((i for i, busy in enumerate(active) if not busy), -1)
            self.assertEqual(self.select(KNOWN, active), expected)
            self.assertEqual(self.select(KNOWN, active, pairing=False), -1)

    def test_unused_reservation_is_preferred_before_old_disconnected_remote(self):
        for empty in range(4):
            addresses = KNOWN.copy()
            addresses[empty] = bytes(6)
            self.assertEqual(self.select(addresses, [False] * 4), empty)
            active = [False] * 4
            active[empty] = True
            expected = next(i for i in range(4) if i != empty)
            self.assertEqual(self.select(addresses, active), expected)

    def test_invalid_remote_addresses_are_rejected(self):
        for invalid in (bytes(6), b"\xff" * 6):
            self.assertEqual(self.select(KNOWN, [False] * 4, invalid), -1)

    def test_successful_replace_persists_one_whole_table_before_publishing(self):
        self.uc.mem_write(TABLE, b"".join(KNOWN))
        self.uc.mem_write(REMOTE, OTHER)
        self.uc.mem_write(SAVED, b"\xa5" * 24)
        self.assertEqual(self.invoke("ss8_commit", TABLE, 2, REMOTE, SAVED, 1), 3)
        expected = b"".join(KNOWN[:2] + [OTHER] + KNOWN[3:])
        self.assertEqual(bytes(self.uc.mem_read(TABLE, 24)), expected)
        self.assertEqual(bytes(self.uc.mem_read(SAVED, 24)), expected)

    def test_failed_persistence_keeps_previous_live_table(self):
        previous = b"".join(KNOWN)
        self.uc.mem_write(TABLE, previous)
        self.uc.mem_write(REMOTE, OTHER)
        self.assertEqual(self.invoke("ss8_commit", TABLE, 1, REMOTE, SAVED, 0), 2)
        self.assertEqual(bytes(self.uc.mem_read(TABLE, 24)), previous)

    def test_reconnect_does_not_rewrite_nvs(self):
        self.uc.mem_write(TABLE, b"".join(KNOWN))
        self.uc.mem_write(REMOTE, KNOWN[3])
        self.uc.mem_write(SAVED, b"\xa5" * 24)
        self.assertEqual(self.invoke("ss8_commit", TABLE, 3, REMOTE, SAVED, 0), 1)
        self.assertEqual(bytes(self.uc.mem_read(SAVED, 24)), b"\xa5" * 24)

    def test_invalid_commit_does_not_change_live_or_persisted_state(self):
        previous = b"".join(KNOWN)
        for slot, remote in ((4, OTHER), (0xFFFFFFFF, OTHER), (0, bytes(6)), (0, b"\xff" * 6)):
            self.uc.mem_write(TABLE, previous)
            self.uc.mem_write(REMOTE, remote)
            self.uc.mem_write(SAVED, b"\xa5" * 24)
            self.assertEqual(self.invoke("ss8_commit", TABLE, slot, REMOTE, SAVED, 1), 0)
            self.assertEqual(bytes(self.uc.mem_read(TABLE, 24)), previous)
            self.assertEqual(bytes(self.uc.mem_read(SAVED, 24)), b"\xa5" * 24)


if __name__ == "__main__":
    unittest.main()
