"""Execute production PPC culling and compare the original PAL animation gate."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import random
import re
import struct
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
try:
    import mkwdis
    import unicorn
    from unicorn import ppc_const as PPC
except ImportError:
    mkwdis = unicorn = PPC = None

CODE, STOP, CLIP, STACK = 0x81700000, 0x8170FFF0, 0x90010000, 0x901F0000
DRIVER = 0x90020000
ORIGINAL_MINIMUM = 0x80787D18
TRICK_CALLBACK, TRICK_SCHEDULE = 0x807D18EC, 0x807D1924


def fbits(value):
    return struct.unpack(">I", struct.pack(">f", value))[0]


def build_harness():
    compiler = ROOT / "tools/cw-wii17/mwcceppc.exe"
    linker = ROOT / "tools/kamek/Kamek.exe"
    for tool in (compiler, linker):
        if not tool.is_file():
            raise unittest.SkipTest(f"required PPC build tool unavailable: {tool}")
    engine = ROOT / "external/rr-pulsar/PulsarEngine"
    game = ROOT / "external/rr-pulsar/GameSource"
    harness = Path(__file__).with_name("clip_distance_harness.cpp")
    output = ROOT / "build/wiimote-tests/clip-distance"
    output.mkdir(parents=True, exist_ok=True)
    obj, binary, mapping, stamp = [output / name for name in (
        "clip.o", "clip.bin", "clip.map", "build.sha256")]
    flags = ["-I-", "-i", str(ROOT / "external/rr-pulsar/KamekInclude"),
             "-i", str(game), "-i", str(engine), "-proc", "gekko", "-fp", "hard",
             "-sdata", "0", "-sdata2", "0", "-opt", "all", "-inline", "auto", "-enum", "int"]
    fingerprint = hashlib.sha256(repr(flags).encode())
    for path in (harness, engine / "SplitScreen8/Culling.cpp", engine / "SplitScreen8/SplitScreen8.hpp",
                 game / "symbols.txt"):
        fingerprint.update(path.read_bytes())
    for tool in (compiler, linker):
        fingerprint.update(f"{tool}:{tool.stat().st_size}:{tool.stat().st_mtime_ns}".encode())
    digest = fingerprint.hexdigest()
    if not (binary.is_file() and mapping.is_file() and stamp.is_file()
            and stamp.read_text().strip() == digest):
        for command in (
            [str(compiler), *flags, "-c", str(harness), "-o", str(obj)],
            [str(linker), str(obj), f"-static=0x{CODE:08x}", f"-externals={game / 'symbols.txt'}",
             f"-output-code={binary}", f"-output-map={mapping}"],
        ):
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=60)
            if result.returncode:
                raise AssertionError("culling PPC harness failed:\n" + result.stdout + result.stderr)
        stamp.write_text(digest + "\n", encoding="ascii")
    exports = {}
    for line in mapping.read_text().splitlines():
        columns = line.split()
        if len(columns) == 3 and re.fullmatch(r"[0-9A-Fa-f]{8}", columns[0]):
            exports[columns[2]] = int(columns[0], 16)
    return binary.read_bytes(), exports


class ClipDistancePpcTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if unicorn is None:
            raise unittest.SkipTest("Unicorn/capstone unavailable")
        cls.code, cls.exports = build_harness()
        cls.minimum = cls.exports["ss8_clip_minimum"]

    def setUp(self):
        self.uc = unicorn.Uc(unicorn.UC_ARCH_PPC, unicorn.UC_MODE_PPC32 | unicorn.UC_MODE_BIG_ENDIAN)
        self.uc.reg_write(PPC.UC_PPC_REG_MSR, 0x2000)
        self.uc.mem_map(0x80000000, 0x1800000)
        self.uc.mem_map(0x90000000, 0x200000)
        self.uc.mem_write(CODE, self.code)

    def distances(self, native, extra):
        self.uc.mem_write(CLIP + 0xC, struct.pack(">4I", *native))
        self.uc.mem_write(CLIP + 0x480C, struct.pack(">4I", *extra))

    def invoke(self, address, *args, stop=STOP):
        self.uc.reg_write(PPC.UC_PPC_REG_1, STACK)
        self.uc.reg_write(PPC.UC_PPC_REG_LR, STOP)
        for index, value in enumerate(args, 3):
            self.uc.reg_write(getattr(PPC, f"UC_PPC_REG_{index}"), value)
        self.uc.emu_start(address, stop, count=10000)
        self.assertEqual(self.uc.reg_read(PPC.UC_PPC_REG_PC), stop)
        return self.uc.reg_read(PPC.UC_PPC_REG_3) & 0xFFFFFFFF

    def test_extra_screen_distances_count_only_in_active_wide_race(self):
        far = list(map(fbits, (1000000, 2000000, 3000000, 4000000)))
        self.distances(far, list(map(fbits, (25, 16, 1, 0))))
        for count in (0, 1, 2, 3, 4):
            self.assertEqual(self.invoke(self.minimum, CLIP, count), far[0])
        for count, value in ((5, 25), (6, 16), (7, 1), (8, 0), (255, 0)):
            self.assertEqual(self.invoke(self.minimum, CLIP, count), fbits(value))

    def test_native_near_screen_still_wins_when_extra_screens_are_far(self):
        self.distances(list(map(fbits, (100, 4, 81, 16))), [fbits(1000000)] * 4)
        for count in (0, 4, 6, 8):
            self.assertEqual(self.invoke(self.minimum, CLIP, count), fbits(4))

    def test_shadow_nan_is_ignored_and_native_first_nan_remains_unchanged(self):
        nan = fbits(float("nan"))
        self.distances([fbits(100)] * 4, [nan, fbits(4), fbits(0), fbits(0)])
        self.assertEqual(self.invoke(self.minimum, CLIP, 5), fbits(100))
        self.assertEqual(self.invoke(self.minimum, CLIP, 6), fbits(4))
        self.distances([nan, fbits(1), fbits(2), fbits(3)], [fbits(0)] * 4)
        self.assertEqual(self.invoke(self.minimum, CLIP, 8), nan)


class OriginalPalClipDistanceTests(ClipDistancePpcTests):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        root = os.environ.get("MKW_PAL_RESOURCE_ROOT")
        if not root:
            raise unittest.SkipTest("set MKW_PAL_RESOURCE_ROOT for original PAL comparisons")
        cls.image = mkwdis.Image()
        mkwdis.load_dol(cls.image, Path(root) / "sys/main.dol")
        mkwdis.load_rel(cls.image, Path(root) / "files/rel/StaticR.rel", mkwdis.REL_BASE)
        if cls.image.read32(ORIGINAL_MINIMUM) != 0xC023000C:
            raise AssertionError("original PAL ClipInfo minimum does not match expected entry")

    def setUp(self):
        super().setUp()
        for address, data, _ in self.image.segments:
            self.uc.mem_write(address, bytes(data))
        self.uc.mem_write(CODE, self.code)

    def original_minimum_bits(self):
        self.invoke(ORIGINAL_MINIMUM, CLIP)
        bits = self.uc.reg_read(PPC.UC_PPC_REG_FPR1)
        return fbits(struct.unpack(">d", struct.pack(">Q", bits))[0])

    def test_native_four_matches_original_order_including_nan_inf_and_signed_zero(self):
        values = [fbits(x) for x in (0.0, -0.0, 1, -1, float("inf"), -float("inf"), float("nan"))]
        rng = random.Random(5318)
        cases = [[values[(i + j) % len(values)] for j in range(4)] for i in range(len(values))]
        cases += [[rng.choice(values) for _ in range(4)] for _ in range(100)]
        cases += [[fbits(rng.uniform(-1e6, 1e6)) for _ in range(4)] for _ in range(100)]
        for native in cases:
            self.distances(native, [fbits(-1e20)] * 4)
            expected = self.original_minimum_bits()
            for count in (0, 4):
                self.assertEqual(self.invoke(self.minimum, CLIP, count), expected, (native, count))

    def test_original_driver_trick_callback_stops_at_far_gate_but_wide_minimum_reaches_schedule(self):
        self.distances([fbits(1000000)] * 4, [fbits(16), fbits(25), fbits(0), fbits(0)])
        self.invoke(self.minimum, CLIP, 6)  # Set production raceScreenCount.
        for wide, scheduled in ((False, False), (True, True)):
            self.uc.mem_write(DRIVER, bytes(0x100))
            self.uc.mem_write(DRIVER + 0xAC, struct.pack(">f", 100))
            self.uc.mem_write(DRIVER + 0xB8, struct.pack(">I", CLIP))
            # Execute the original driver's distance call, squaring of its own
            # cutoff and native comparison/store at 0x807CB2D4..0x807CB2F4.
            def minimum_hook(uc, pc, size, data):
                if wide and pc == ORIGINAL_MINIMUM:
                    uc.reg_write(PPC.UC_PPC_REG_PC, self.exports["ss8_clip_minimum_float"])
            hook = self.uc.hook_add(unicorn.UC_HOOK_CODE, minimum_hook)
            try:
                self.uc.reg_write(PPC.UC_PPC_REG_31, DRIVER)
                self.invoke(0x807CB2D4, stop=0x807CB2F8)
            finally:
                self.uc.hook_del(hook)
            self.assertEqual(bytes(self.uc.mem_read(DRIVER + 0xB4, 1)), bytes([int(not scheduled)]))
            # Run the real callback until it either returns at its native far
            # cutoff or reaches its first scheduling instruction. No fake anim.
            reached = []
            def on_instruction(uc, pc, size, data):
                if pc == TRICK_SCHEDULE:
                    reached.append(pc)
                    uc.emu_stop()
            hook = self.uc.hook_add(unicorn.UC_HOOK_CODE, on_instruction)
            try:
                self.uc.reg_write(PPC.UC_PPC_REG_1, STACK)
                self.uc.reg_write(PPC.UC_PPC_REG_LR, STOP)
                self.uc.reg_write(PPC.UC_PPC_REG_3, DRIVER)
                self.uc.emu_start(TRICK_CALLBACK, STOP, count=1000)
                self.assertEqual(bool(reached), scheduled)
            finally:
                self.uc.hook_del(hook)


if __name__ == "__main__":
    unittest.main()
