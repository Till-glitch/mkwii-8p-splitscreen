"""Compare the actual Wheel port against independent original PAL PPC routines.

Set MKW_PAL_RESOURCE_ROOT to a local RMCP01 directory with sys/main.dol and
files/rel/StaticR.rel. No game assets are committed or downloaded. The compiler
and Unicorn are optional for ordinary source-only test discovery.

Gekko paired-single spills are skipped in the emulator. Original sine/cosine
table lookups use equivalent float32 interpolation because Unicorn cannot run
their quantized loads. This verifies the steering/item pipeline, not rendering,
Bluetooth or end-to-end device latency.
"""

from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path
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

COMPILER = ROOT / "tools/cw-wii17/mwcceppc.exe"
LINKER = ROOT / "tools/kamek/Kamek.exe"
HARNESS = Path(__file__).with_name("wheel_native_harness.cpp")
OUTPUT_DIR = ROOT / "build/wiimote-tests/native-wheel"
ENGINE = ROOT / "external/rr-pulsar/PulsarEngine"
GAME_SOURCE = ROOT / "external/rr-pulsar/GameSource"
CODE, STOP = 0x81700000, 0x8170FFF0
STATE, SNAPSHOT, OUTPUT = 0x90010000, 0x90020000, 0x90030000
REFERENCE, SDK, REFERENCE_INPUT = 0x90040000, 0x90050000, 0x90060000
ITEM, ITEM_INPUT, ITEM_OUTPUT = 0x90070000, 0x90071000, 0x90072000
MANAGER, STACK = 0x90080000, 0x901F0000
SNAPSHOT_RECORD = struct.Struct(">BBHhhhHIIHH")
QUANTIZER_TAIL, QUANTIZER_END = 0x8074604C, 0x807460F0
WHEEL_CONSTANTS = 0x808A2BB8
REL_INITIALIZER = 0x80747154
AUTO_ITEM_MASK = 0x809C2C40
PSQ_SPILLS = {0x805103B4 + offset for offset in (
    0x2365CC, 0x236728, 0x2368C0, 0x2368C8, 0x2368D0,
    0x236D68, 0x236D70, 0x236D78,
)}


def float32(value: float) -> float:
    return struct.unpack(">f", struct.pack(">f", value))[0]


def build_harness() -> tuple[bytes, dict[str, int]]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    obj, binary, mapping, stamp = [OUTPUT_DIR / name for name in (
        "wheel.o", "wheel.bin", "wheel.map", "build.sha256")]
    flags = [
        "-I-", "-i", str(ROOT / "external/rr-pulsar/KamekInclude"),
        "-i", str(GAME_SOURCE), "-i", str(ENGINE), "-i", str(ROOT / "shared"),
        "-proc", "gekko", "-fp", "hard", "-sdata", "0", "-sdata2", "0",
        "-opt", "all", "-inline", "auto", "-enum", "int", "-DSS8_WHEEL_BRIDGE",
    ]
    fingerprint = hashlib.sha256(repr(flags).encode())
    paths = [HARNESS, ENGINE / "SplitScreen8/WheelNative.cpp",
             ENGINE / "SplitScreen8/WheelNative.hpp", GAME_SOURCE / "symbols.txt",
             GAME_SOURCE / "MarioKartWii/Input/InputState.hpp",
             ROOT / "shared/wii_bridge_protocol.h", ROOT / "shared/wheel_bridge_identity.h"]
    for path in paths:
        fingerprint.update(path.read_bytes())
    for tool in (COMPILER, LINKER):
        fingerprint.update(f"{tool}:{tool.stat().st_size}:{tool.stat().st_mtime_ns}".encode())
    digest = fingerprint.hexdigest()
    if not (binary.is_file() and mapping.is_file() and stamp.is_file()
            and stamp.read_text().strip() == digest):
        commands = [
            [str(COMPILER), *flags, "-c", str(HARNESS), "-o", str(obj)],
            [str(LINKER), str(obj), f"-static=0x{CODE:08x}",
             f"-externals={GAME_SOURCE / 'symbols.txt'}",
             f"-output-code={binary}", f"-output-map={mapping}"],
        ]
        for command in commands:
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=60)
            if result.returncode:
                raise AssertionError("native Wheel harness failed:\n" + result.stdout + result.stderr)
        stamp.write_text(digest + "\n", encoding="ascii")
    exports = {}
    for line in mapping.read_text().splitlines():
        columns = line.split()
        if len(columns) == 3 and re.fullmatch(r"[0-9A-Fa-f]{8}", columns[0]):
            exports[columns[2]] = int(columns[0], 16)
    required = {"ss8_wheel_size", "ss8_action_size", "ss8_wheel_reset", "ss8_action_reset",
                "ss8_quantise", "ss8_wheel_step", "ss8_action_step", "ss8_identity_slot_id",
                "ss8_identity_display_id", "ss8_identity_fill"}
    if missing := required - exports.keys():
        raise AssertionError(f"native Wheel harness exports missing: {sorted(missing)}")
    code = binary.read_bytes()
    if len(code) >= STOP - CODE:
        raise AssertionError("native Wheel harness outgrew its code area")
    return code, exports


class WheelIdentityPpcTests(unittest.TestCase):
    """Real PPC identity functions; no Nintendo resources required."""

    @classmethod
    def setUpClass(cls):
        if unicorn is None:
            raise unittest.SkipTest("Unicorn/capstone unavailable; install tools/.venv dependencies")
        for tool in (COMPILER, LINKER):
            if not tool.is_file():
                raise unittest.SkipTest(f"required PPC build tool unavailable: {tool}")
        cls.code, cls.exports = build_harness()

    def setUp(self):
        self.uc = unicorn.Uc(unicorn.UC_ARCH_PPC,
                             unicorn.UC_MODE_PPC32 | unicorn.UC_MODE_BIG_ENDIAN)
        self.uc.mem_map(CODE, 0x10000)
        self.uc.mem_map(0x90000000, 0x200000)
        self.uc.mem_write(CODE, self.code)

    def invoke(self, name: str, *arguments: int) -> int:
        self.uc.reg_write(PPC.UC_PPC_REG_1, STACK)
        self.uc.reg_write(PPC.UC_PPC_REG_LR, STOP)
        for index, value in enumerate(arguments, 3):
            self.uc.reg_write(getattr(PPC, f"UC_PPC_REG_{index}"), value & 0xFFFFFFFF)
        self.uc.emu_start(self.exports[name], STOP, count=10000)
        self.assertEqual(self.uc.reg_read(PPC.UC_PPC_REG_PC), STOP)
        return self.uc.reg_read(PPC.UC_PPC_REG_3) & 0xFFFFFFFF

    def test_private_ids_are_unique_and_disjoint_from_native_registration_ids(self):
        private_ids = [self.invoke("ss8_identity_slot_id", slot) for slot in range(4)]
        self.assertEqual(private_ids, [0x53530001, 0x53530002, 0x53530003, 0x53530004])
        self.assertEqual(len(set(private_ids)), 4)
        self.assertTrue(set(private_ids).isdisjoint({0x111, 0x211, 0x311, 0x411}))
        for invalid in (4, 8, 0xFFFFFFFF):
            self.assertEqual(self.invoke("ss8_identity_slot_id", invalid), 0)

    def test_display_ids_convert_only_private_namespace(self):
        for slot in range(4):
            self.assertEqual(self.invoke("ss8_identity_display_id", 0x53530001 + slot),
                             0x111 + slot * 0x100)
        for passthrough in (0, 0x111, 0x211, 0x311, 0x411, 0x53530000, 0x53530005, 0xFFFFFFFF):
            self.assertEqual(self.invoke("ss8_identity_display_id", passthrough), passthrough)

    def test_proxy_params_have_exact_layout_and_invalid_slot_does_not_write(self):
        addresses = set()
        for slot in range(4):
            self.uc.mem_write(OUTPUT, b"\xa5" * 24)
            self.assertEqual(self.invoke("ss8_identity_fill", OUTPUT + 4, slot), 1)
            address = b"\x02\x53\x53\x38\x00" + bytes([slot + 1])
            expected = b"\xa5" * 4 + struct.pack(">I6s2xI", 0, address, slot) + b"\xa5" * 4
            self.assertEqual(bytes(self.uc.mem_read(OUTPUT, 24)), expected)
            addresses.add(address)
        self.assertEqual(len(addresses), 4)
        for invalid in (4, 0xFFFFFFFF):
            self.uc.mem_write(OUTPUT, b"\xa5" * 24)
            self.assertEqual(self.invoke("ss8_identity_fill", OUTPUT + 4, invalid), 0)
            self.assertEqual(bytes(self.uc.mem_read(OUTPUT, 24)), b"\xa5" * 24)


class WheelNativePpcTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        resource_root = os.environ.get("MKW_PAL_RESOURCE_ROOT")
        if not resource_root:
            raise unittest.SkipTest(
                "set MKW_PAL_RESOURCE_ROOT to local RMCP01 resources for native Wheel comparisons")
        if unicorn is None:
            raise unittest.SkipTest("Unicorn/capstone unavailable; install tools/.venv dependencies")
        for tool in (COMPILER, LINKER):
            if not tool.is_file():
                raise unittest.SkipTest(f"required PPC build tool unavailable: {tool}")
        cls.resource_root = Path(resource_root)
        dol = cls.resource_root / "sys/main.dol"
        rel = cls.resource_root / "files/rel/StaticR.rel"
        for path in (dol, rel):
            if not path.is_file():
                raise AssertionError(f"configured PAL resource missing: {path}")
        cls.image = mkwdis.Image()
        mkwdis.load_dol(cls.image, dol)
        mkwdis.load_rel(cls.image, rel, mkwdis.REL_BASE)
        # Refuse an incompatible resource before executing hard PAL entrypoints.
        expected_call = 0x48000001 | ((0x8051FBE0 - 0x8051FE4C) & 0x03FFFFFC)
        if cls.image.read32(0x8051FE4C) != expected_call:
            raise AssertionError("resources do not match the PAL native Wheel callsite")
        cls.code, cls.exports = build_harness()

    def setUp(self):
        self.uc = unicorn.Uc(unicorn.UC_ARCH_PPC,
                             unicorn.UC_MODE_PPC32 | unicorn.UC_MODE_BIG_ENDIAN)
        self.uc.reg_write(PPC.UC_PPC_REG_MSR, 0x2000)  # enable PPC floating point
        self.uc.mem_map(0x80000000, 0x1800000)
        self.uc.mem_map(0x90000000, 0x200000)
        for address, data, _ in self.image.segments:
            self.uc.mem_write(address, bytes(data))
        self.uc.mem_write(CODE, self.code)
        self.uc.hook_add(unicorn.UC_HOOK_CODE, self.emulator_service)
        self.uc.reg_write(PPC.UC_PPC_REG_2, 0x8038EFA0)
        self.uc.reg_write(PPC.UC_PPC_REG_13, 0x8038CC00)
        self.write_word(0x809BD70C, MANAGER)
        self.uc.mem_write(0x8034587C, struct.pack(">ff", 0.3, 0.5))
        self.write_word(0x80345D14, 0)
        self.uc.mem_write(0x802A4100, bytes(12))
        self.uc.mem_write(0x802A4118, struct.pack(">3f", 1, 0, 0))
        # Execute the game's actual REL initializer, rather than assuming all
        # BSS is zero during gameplay. In particular, it sets the auto item mask.
        self.invoke(REL_INITIALIZER)
        self.assertEqual(bytes(self.uc.mem_read(AUTO_ITEM_MASK, 2)), b"\x04\x0c")

    def write_word(self, address: int, value: int):
        self.uc.mem_write(address, struct.pack(">I", value & 0xFFFFFFFF))

    def read_fpr(self, index: int) -> float:
        bits = self.uc.reg_read(getattr(PPC, f"UC_PPC_REG_FPR{index}"))
        return struct.unpack(">d", struct.pack(">Q", bits))[0]

    def write_fpr(self, index: int, value: float):
        bits = struct.unpack(">Q", struct.pack(">d", value))[0]
        self.uc.reg_write(getattr(PPC, f"UC_PPC_REG_FPR{index}"), bits)

    def emulator_service(self, uc, pc, size, user_data):
        if pc == QUANTIZER_END:
            uc.reg_write(PPC.UC_PPC_REG_PC, STOP)
        elif pc in (0x80085110, 0x80085180):
            value = self.read_fpr(1)
            angle = abs(value)
            while angle > 256:
                angle = float32(angle - 256)
            index = int(angle) & 255
            fraction = float32(angle - int(angle))
            offset = 0 if pc == 0x80085110 else 4
            base = 0x80248010 + index * 16 + offset
            start = struct.unpack(">f", bytes(uc.mem_read(base, 4)))[0]
            delta = struct.unpack(">f", bytes(uc.mem_read(base + 8, 4)))[0]
            result = float32(start + float32(fraction * delta))
            if pc == 0x80085110 and value < 0:
                result = -result
            self.write_fpr(1, result)
            uc.reg_write(PPC.UC_PPC_REG_PC, uc.reg_read(PPC.UC_PPC_REG_LR))
        elif pc in PSQ_SPILLS:
            uc.reg_write(PPC.UC_PPC_REG_PC, pc + 4)

    def invoke(self, function: str | int, *arguments: int,
               f1: float | None = None, registers: dict[int, int] | None = None) -> int:
        self.uc.reg_write(PPC.UC_PPC_REG_1, STACK)
        self.uc.reg_write(PPC.UC_PPC_REG_LR, STOP)
        for index, value in enumerate(arguments, 3):
            self.uc.reg_write(getattr(PPC, f"UC_PPC_REG_{index}"), value & 0xFFFFFFFF)
        if f1 is not None:
            self.write_fpr(1, f1)
        if registers:
            for index, value in registers.items():
                self.uc.reg_write(getattr(PPC, f"UC_PPC_REG_{index}"), value & 0xFFFFFFFF)
        address = self.exports[function] if isinstance(function, str) else function
        try:
            self.uc.emu_start(address, STOP, count=1_000_000)
        except unicorn.UcError as error:
            pc = self.uc.reg_read(PPC.UC_PPC_REG_PC)
            lr = self.uc.reg_read(PPC.UC_PPC_REG_LR)
            self.fail(f"native Wheel {function} failed at pc={pc:08x}, lr={lr:08x}: {error}")
        self.assertEqual(self.uc.reg_read(PPC.UC_PPC_REG_PC), STOP, "instruction budget exhausted")
        return self.uc.reg_read(PPC.UC_PPC_REG_3) & 0xFFFFFFFF

    def write_snapshot(self, vector=(128, 0, 0), sequence=1, diagnostic_trick=0):
        self.uc.mem_write(SNAPSHOT, SNAPSHOT_RECORD.pack(
            0, 7, 0, *vector, 0, sequence, 0, diagnostic_trick, 0))

    def original_quantizer(self, bits: int, mirror=False, reference=REFERENCE) -> int:
        self.write_word(reference + 0x54, bits)
        self.uc.mem_write(OUTPUT + 0x100, bytes(24))
        self.uc.mem_write(REFERENCE_INPUT, bytes(24))
        self.uc.mem_write(MANAGER + 0x4155, bytes([mirror]))
        self.invoke(QUANTIZER_TAIL, registers={
            26: reference, 27: OUTPUT + 0x100, 28: REFERENCE_INPUT, 30: WHEEL_CONSTANTS})
        return self.uc.mem_read(OUTPUT + 0x110, 1)[0]

    def test_private_state_sizes_and_resets(self):
        self.assertEqual(self.invoke("ss8_wheel_size"), 0x5F4)
        self.assertEqual(self.invoke("ss8_action_size"), 0x24)
        self.uc.mem_write(STATE, b"\xff" * 0x5F4)
        self.invoke("ss8_wheel_reset", STATE)
        self.assertEqual(bytes(self.uc.mem_read(STATE, 0x5F4)), bytes(0x5F4))
        self.uc.mem_write(STATE, b"\xff" * 0x24)
        self.invoke("ss8_action_reset", STATE)
        self.assertEqual(bytes(self.uc.mem_read(STATE, 0x24)), bytes(0x24))

    def test_quantizer_matches_original_tail_at_boundaries_and_nonfinite_values(self):
        bits = [0, 0x80000000, 0x7FC00000, 0x7F800000, 0xFF800000, 0x7F7FFFFF, 0xFF7FFFFF]
        values = [n / 7.56 for n in range(-16, 17)]
        values += [-0.926, -0.925, -0.1323, -0.1322, 0.1322, 0.1323, 0.925, 0.926, 1.0, -1.0]
        bits += [struct.unpack(">I", struct.pack(">f", value))[0] for value in values]
        for value in bits:
            with self.subTest(bits=f"{value:08x}"):
                self.assertEqual(self.invoke("ss8_quantise", value), self.original_quantizer(value))
        self.assertEqual(len(bits), 50)

    def test_four_private_steering_states_match_independent_original_pipeline(self):
        trace = [(128, 0, 0)] * 30
        angles = list(range(-85, 86, 5)) + list(range(85, -86, -5))
        trace += [(round(128 * math.cos(math.radians(angle))), 0,
                   round(128 * math.sin(math.radians(angle)))) for angle in angles]
        trace += [(0, 0, 350)] * 8 + [(-128, 0, 0)] * 8 + [(0, 0, 0)] * 8 + [(128, 0, 0)] * 40
        checks = 0
        for mirror in (False, True):
            for auto in (False, True):
                for slot in range(4):
                    state, reference, sdk = STATE + slot * 0x1000, REFERENCE + slot * 0x100, SDK + slot * 0x600
                    self.invoke("ss8_wheel_reset", state)
                    self.uc.mem_write(reference, bytes(0x90))
                    self.uc.mem_write(sdk, bytes(0x538))
                    self.uc.mem_write(sdk + 0x9C, struct.pack(">ff", 0.3, 0.5))
                    self.invoke(0x80746AFC, reference, reference + 0x18, int(auto))
                for sequence, axis in enumerate(trace, 1):
                    vectors = [axis, (axis[0], axis[1], -axis[2]),
                               (axis[0], axis[1], axis[2] // 2), (0, -128, axis[2])]
                    for slot, vector in enumerate(vectors):
                        state = STATE + slot * 0x1000
                        reference, sdk = REFERENCE + slot * 0x100, SDK + slot * 0x600
                        self.uc.mem_write(MANAGER + 0x4155, bytes([mirror]))
                        self.write_snapshot(vector, sequence)
                        self.invoke("ss8_wheel_step", state, SNAPSHOT, 0x100, int(auto), 0, OUTPUT)
                        filtered = []
                        for component, value in enumerate(vector):
                            address = sdk + 0x0C + component * 4
                            self.invoke(0x8019548C, sdk, address, f1=value / 128)
                            filtered.append(struct.unpack(">f", bytes(self.uc.mem_read(address, 4)))[0])
                        self.uc.mem_write(REFERENCE_INPUT, struct.pack(">IIIfff", 0x100, 0, 0, *filtered))
                        self.invoke(0x80746C64, reference, reference + 0x18, REFERENCE_INPUT)
                        steering = struct.unpack(">I", bytes(self.uc.mem_read(reference + 0x54, 4)))[0]
                        expected = self.original_quantizer(steering, mirror, reference)
                        actual = self.uc.mem_read(OUTPUT + 0x10, 1)[0]
                        self.assertEqual(actual, expected, (slot, mirror, auto, sequence, vector))
                        self.assertEqual(bytes(self.uc.mem_read(OUTPUT + 8, 4)),
                                         bytes(self.uc.mem_read(OUTPUT + 0x108, 4)))
                        self.assertEqual(bytes(self.uc.mem_read(OUTPUT + 4, 2)), b"\x00\x01")
                        checks += 1
        self.assertEqual(checks, 2624)

    def test_item_actions_match_independent_original_decoders_and_keep_native_x_flick(self):
        # Explicit desired physical -> native Wheel actions, independent of production mapping.
        trace = [(0, 0)]
        trace += [(0x400, 4)] * 8 + [(0x401, 1)] * 6 + [(0x400, 4)] * 3 + [(0, 0)] * 5
        trace += [(0x400, 4)] * 8 + [(0x402, 2)] * 6 + [(0, 0)] * 5
        trace += [(4, 4)] * 12 + [(0, 0)] * 5 + [(8, 8)] * 12 + [(0, 0)] * 5
        trace += [(1, 1)] * 8 + [(0, 0)] * 5 + [(2, 2)] * 8 + [(0, 0)] * 5
        trace += [(0x400, 4)] * 5 + [(0x402, 2), (0x400, 4)] + [(0, 0)] * 5
        trace += [(0x400, 4)] * 5 + [(0x401, 1), (0x400, 4)] + [(0, 0)] * 5
        checks = 0
        for mirror in (False, True):
            self.uc.mem_write(MANAGER + 0x4155, bytes([mirror]))
            for auto in (False, True):
                self.invoke("ss8_action_reset", STATE)
                self.uc.mem_write(ITEM, bytes(0x20))
                previous = 0
                outputs = []
                for index, (physical, equivalent) in enumerate(trace):
                    self.uc.mem_write(OUTPUT, struct.pack(
                        ">IHHffBBBBBBBB", 0, 0, 0, 0.42, 0, 10, 7, 3, 3, 0x80, 0, 0, 0))
                    before = bytes(self.uc.mem_read(OUTPUT, 24))
                    self.invoke("ss8_action_step", STATE, physical | 0x900, int(auto), OUTPUT)
                    self.uc.mem_write(ITEM_INPUT, struct.pack(
                        ">III", equivalent, equivalent & ~previous, previous & ~equivalent))
                    self.uc.mem_write(ITEM_OUTPUT, b"\x00\x21\x07")
                    self.invoke(0x807462B8 if auto else 0x8074612C,
                                ITEM, ITEM_OUTPUT, ITEM_INPUT, ITEM_OUTPUT + 2)
                    self.assertEqual(bytes(self.uc.mem_read(OUTPUT + 4, 2)),
                                     bytes(self.uc.mem_read(ITEM_OUTPUT, 2)), (auto, index, physical))
                    self.assertEqual(bytes(self.uc.mem_read(OUTPUT + 0x11, 1)),
                                     bytes(self.uc.mem_read(ITEM_OUTPUT + 2, 1)))
                    self.assertEqual(bytes(self.uc.mem_read(OUTPUT + 8, 4)), before[8:12])
                    self.assertEqual(bytes(self.uc.mem_read(OUTPUT + 0x10, 1)), before[16:17])
                    self.assertEqual(bytes(self.uc.mem_read(OUTPUT + 0x12, 2)), before[18:20])
                    actions = int.from_bytes(self.uc.mem_read(OUTPUT + 4, 2), "big")
                    outputs.append((actions & 4, self.uc.mem_read(OUTPUT + 0x11, 1)[0]))
                    previous = equivalent
                    checks += 1
                self.assertTrue(all(value[0] == 4 for value in outputs[1:9]), "long B hold")
                self.assertEqual(outputs[9], (4, 0), "B + back direction acts immediately")
                self.assertEqual(outputs[10], (0, 0), "native one-shot and direction retention")
        self.assertEqual(checks, 504)

    def test_desired_hop_latch_rearview_and_drift_mode_reset(self):
        self.invoke("ss8_action_reset", STATE)
        for raw, expected in [(0, 0), (0x100, 1), (0x300, 11), (0x300, 11),
                              (0x100, 1), (0x200, 2), (0x300, 3), (0, 0), (0x800, 0x20)]:
            self.invoke("ss8_action_step", STATE, raw, 0, OUTPUT)
            self.assertEqual(int.from_bytes(self.uc.mem_read(OUTPUT + 4, 2), "big"), expected)
        for auto in (0, 1, 0):
            self.invoke("ss8_action_step", STATE, 0x400, auto, OUTPUT)
            self.assertEqual(int.from_bytes(self.uc.mem_read(OUTPUT + 4, 2), "big") & 4, 4)

    def test_diagnostic_trick_flag_is_ignored_and_flick_mirrored_once(self):
        self.invoke("ss8_wheel_reset", STATE)
        self.write_snapshot(diagnostic_trick=1)
        self.invoke("ss8_wheel_step", STATE, SNAPSHOT, 0x100, 0, 0, OUTPUT)
        self.assertEqual(bytes(self.uc.mem_read(OUTPUT + 0x12, 2)), b"\0\0")
        for mirror in (False, True):
            self.uc.mem_write(MANAGER + 0x4155, bytes([mirror]))
            for pulse in range(5):
                self.invoke("ss8_wheel_step", STATE, SNAPSHOT, 0x100, 0, pulse, OUTPUT)
                expected = {3: 4, 4: 3}.get(pulse, pulse) if mirror else pulse
                self.assertEqual(bytes(self.uc.mem_read(OUTPUT + 0x12, 2)), bytes([expected, pulse]))


if __name__ == "__main__":
    if "--pal-resource-root" in sys.argv:
        index = sys.argv.index("--pal-resource-root")
        if index + 1 >= len(sys.argv):
            raise SystemExit("--pal-resource-root requires an RMCP01 directory")
        os.environ["MKW_PAL_RESOURCE_ROOT"] = sys.argv[index + 1]
        del sys.argv[index:index + 2]
    unittest.main()
