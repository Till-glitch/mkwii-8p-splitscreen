"""Wire-contract tests; run with python -m unittest discover -s tools/wiimote_tests.

No game data, serial hardware or third-party Python packages are required.
The optional native C++ parity test needs g++/clang++ (or CXX pointing at one).
"""

from __future__ import annotations

import binascii
from dataclasses import replace
import os
from pathlib import Path
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from wiimote_bridge.protocol import (  # noqa: E402
    ACK_RECORD, HEADER, HEADER_SIZE, MAX_FRAME_SIZE, MAX_PAYLOAD,
    FLAG_CONNECTED, FLAG_EVENT_OVERFLOW, SNAPSHOT_RECORD,
    DeviceRecord, EventAck, EventKind, Frame, InputEvent, LegacySnapshot,
    MessageKind, ProtocolError, SnapshotSlot, StreamParser,
    crc16, decode_frame, decode_w2, encode_frame,
)


def snapshot() -> Frame:
    return Frame(MessageKind.SNAPSHOT, 0x01020304, 5, 6, (
        SnapshotSlot(0, 7, 0x0100, -512, 0, 511, 1, 17, 34, 1),
        SnapshotSlot(1, 0, 0, 0, 0, 0, 0xFFFF, 0, 0),
        SnapshotSlot(2, 15, 0x1234, -1, 128, -128, 250, 0xFFFFFFFF, 0x80000000),
        SnapshotSlot(3, 1, 0, 0, 0, 0, 0, 0, 0),
    ))


def examples() -> tuple[Frame, ...]:
    return (
        snapshot(),
        Frame(MessageKind.DEVICES, 0x01020304, 7, 8, tuple(
            DeviceRecord(i, i % 2, bytes((0x11, 0x22, 0x33, 0x44, 0x55, i))) for i in range(4)
        )),
        Frame(MessageKind.EVENTS, 0x01020304, 9, 10, (
            InputEvent(0, EventKind.BUTTONS, 0x0100, 0xFFFFFFFF, 0xFFFFFFFF, 100),
            InputEvent(0, EventKind.BUTTONS, 0, 0, 0, 101),
            InputEvent(0, EventKind.TRICK, 1, 1, 1, 102),
            InputEvent(3, EventKind.BUTTONS, 0x0400, 7, 11, 103),
        )),
        Frame(MessageKind.ACK, 0x01020304, 5, 6, (EventAck(0, 7),)),
    )


def with_crc(body: bytes | bytearray) -> bytes:
    """Independent stdlib CRC implementation for constructing malformed frames."""
    return bytes(body) + struct.pack(">H", binascii.crc_hqx(body, 0xFFFF))


def legacy_packet() -> bytes:
    # Explicit W2 signed-ten-bit vector, not the implementation's encoder.
    body = bytearray(b"W2\x09\x00" + bytes(28))
    for slot_id in range(4):
        offset = 4 + slot_id * 7
        body[offset:offset + 7] = bytes((0x01, 0x02, 0, 0xFF, 0x80, 0xC6, slot_id))
        # packed high bits: X=10 -> -512, Y=01 -> +511, Z=00 -> +128
    checksum = body[2]
    for byte in body[4:]:
        checksum ^= byte
    body[3] = checksum
    return bytes(body)


class CodecTests(unittest.TestCase):
    def test_layout_and_known_crc(self):
        self.assertEqual(HEADER_SIZE, 18)
        self.assertEqual(SNAPSHOT_RECORD.size, 24)
        self.assertEqual(ACK_RECORD.size, 8)
        self.assertEqual(MAX_FRAME_SIZE, 532)
        self.assertEqual(crc16(b"123456789"), 0x29B1)

    def test_independent_crc_for_random_bytes(self):
        rng = random.Random(0xC0DE)
        for size in (0, 1, 17, 18, 96, 512, 530):
            data = bytes(rng.randrange(256) for _ in range(size))
            self.assertEqual(crc16(data), binascii.crc_hqx(data, 0xFFFF))

    def test_ack_golden_vector(self):
        golden = bytes.fromhex("57330104000801020304000000050000000600000000000000078106")
        self.assertEqual(encode_frame(examples()[-1]), golden)
        self.assertEqual(decode_frame(golden), examples()[-1])

    def test_snapshot_wire_offsets(self):
        encoded = encode_frame(snapshot())
        self.assertEqual(len(encoded), 116)
        self.assertEqual(encoded[:18].hex(), "573301010060010203040000000500000006")
        self.assertEqual(encoded[18:42].hex(), "00070100fe00000001ff0001000000110000002200010000")
        self.assertEqual(decode_frame(encoded), snapshot())

    def test_roundtrip_all_kinds_and_views(self):
        for frame in examples():
            with self.subTest(kind=frame.kind):
                data = encode_frame(frame)
                for source in (data, bytearray(data), memoryview(data)):
                    self.assertEqual(decode_frame(source), frame)

    def test_every_single_byte_corruption_rejected(self):
        for frame in examples():
            encoded = encode_frame(frame)
            for index in range(len(encoded)):
                broken = bytearray(encoded)
                broken[index] ^= 1
                with self.subTest(kind=frame.kind, index=index), self.assertRaises(ProtocolError):
                    decode_frame(broken)

    def test_truncation_and_extra_data_rejected(self):
        encoded = encode_frame(snapshot())
        for size in range(len(encoded)):
            with self.subTest(size=size), self.assertRaises(ProtocolError):
                decode_frame(encoded[:size])
        with self.assertRaises(ProtocolError):
            decode_frame(encoded + b"\x00")

    def test_unsupported_version_and_kind(self):
        base = bytearray(encode_frame(examples()[-1])[:-2])
        for offset, value in ((2, 2), (3, 0), (3, 5), (3, 255)):
            broken = base.copy()
            broken[offset] = value
            with self.assertRaises(ProtocolError):
                decode_frame(with_crc(broken))

    def test_invalid_lengths(self):
        for kind, length in ((1, 24), (2, 8), (3, 0), (3, 17), (4, 0), (4, 40), (3, 513)):
            malformed = HEADER.pack(b"W3", 1, kind, length, 1, 1, 1) + bytes(length)
            with self.subTest(kind=kind, length=length), self.assertRaises(ProtocolError):
                decode_frame(with_crc(malformed))

    def test_bad_snapshot_flags_axis_reserved_and_slot(self):
        base = bytearray(encode_frame(snapshot())[:-2])
        for relative, value in ((0, 4), (1, 16), (20, 1), (22, 1)):
            broken = base.copy()
            broken[18 + relative] = value
            with self.subTest(relative=relative), self.assertRaises(ProtocolError):
                decode_frame(with_crc(broken))
        for value in (-513, 512, 32767, -32768):
            broken = base.copy()
            struct.pack_into(">h", broken, 22, value)
            with self.assertRaises(ProtocolError):
                decode_frame(with_crc(broken))

    def test_duplicate_or_missing_slot_rejected(self):
        for original in (snapshot(), examples()[1]):
            records = list(original.records)
            records[-1] = replace(records[-1], slot_id=0)
            with self.assertRaises(ProtocolError):
                encode_frame(replace(original, records=tuple(records)))
        with self.assertRaises(ProtocolError):
            encode_frame(replace(snapshot(), records=snapshot().records[:3]))

    def test_ack_reserved_and_duplicates_rejected(self):
        base = bytearray(encode_frame(examples()[-1])[:-2])
        for offset in (19, 20, 21):
            broken = base.copy()
            broken[offset] = 1
            with self.assertRaises(ProtocolError):
                decode_frame(with_crc(broken))
        with self.assertRaises(ProtocolError):
            encode_frame(replace(examples()[-1], records=(EventAck(1, 1), EventAck(1, 2))))

    def test_event_order_and_repeated_slots_preserved(self):
        frame = examples()[2]
        self.assertEqual(decode_frame(encode_frame(frame)).records, frame.records)
        self.assertEqual([event.event_sequence for event in frame.records[:3]], [0xFFFFFFFF, 0, 1])
        with self.assertRaises(ProtocolError):
            encode_frame(replace(frame, records=(replace(frame.records[0], event_kind=3),)))

    def test_invalid_integer_types_and_bounds_rejected(self):
        for changed in (replace(snapshot(), boot_session=-1), replace(snapshot(), sender_time_ms=0x100000000)):
            with self.assertRaises(ProtocolError):
                encode_frame(changed)
        for changed in (replace(snapshot().records[0], buttons=True), replace(snapshot().records[0], sample_age_ms=65536)):
            with self.assertRaises(ProtocolError):
                encode_frame(replace(snapshot(), records=(changed,) + snapshot().records[1:]))
        with self.assertRaises(ProtocolError):
            encode_frame(replace(snapshot(), records=("not a record",) * 4))

    def test_maximum_event_frame(self):
        event = examples()[2].records[0]
        frame = replace(examples()[2], records=tuple(replace(event, event_sequence=i) for i in range(32)))
        self.assertEqual(len(encode_frame(frame)), MAX_FRAME_SIZE)
        self.assertEqual(decode_frame(encode_frame(frame)), frame)
        with self.assertRaises(ProtocolError):
            encode_frame(replace(frame, records=frame.records + (event,)))

    def test_overflow_is_explicit_diagnostic_flag(self):
        changed = replace(snapshot().records[0], flags=FLAG_CONNECTED | FLAG_EVENT_OVERFLOW)
        frame = replace(snapshot(), records=(changed,) + snapshot().records[1:])
        self.assertEqual(decode_frame(encode_frame(frame)).records[0].flags, 9)


class LegacyTests(unittest.TestCase):
    def test_signed_axes_and_flags(self):
        frame = decode_w2(legacy_packet())
        self.assertEqual(frame.connected_mask, 9)
        for slot in frame.slots:
            self.assertEqual((slot.accel_x, slot.accel_y, slot.accel_z), (-512, 511, 128))
            self.assertEqual(slot.buttons, 0x0102)
            self.assertTrue(slot.calibrated)
            self.assertTrue(slot.trick)
            self.assertEqual(slot.sequence, slot.slot_id)
            self.assertEqual(slot.connected, slot.slot_id in (0, 3))

    def test_neutral_packet(self):
        self.assertEqual(decode_w2(b"W2" + bytes(30)).connected_mask, 0)

    def test_bad_legacy_packets(self):
        original = legacy_packet()
        bad_mask = bytearray(original)
        bad_mask[2] ^= 16
        bad_mask[3] ^= 16
        for data in (original[:-1], original + b"\x00", b"WM" + original[2:], bad_mask):
            with self.assertRaises(ProtocolError):
                decode_w2(data)
        for index in (2, 3, 4, 31):
            bad = bytearray(original)
            bad[index] ^= 1
            with self.assertRaises(ProtocolError):
                decode_w2(bad)


class StreamTests(unittest.TestCase):
    def test_every_split_position(self):
        frames = examples()
        encoded = b"".join(encode_frame(frame) for frame in frames)
        for split in range(len(encoded) + 1):
            parser = StreamParser()
            with self.subTest(split=split):
                self.assertEqual(parser.feed(encoded[:split]) + parser.feed(encoded[split:]), list(frames))
                self.assertEqual(parser.buffered_bytes, 0)

    def test_single_byte_feeds_and_noise(self):
        parser = StreamParser()
        decoded = []
        data = b"boot message\r\nWW\x00W" + encode_frame(snapshot()) + b"done"
        for byte in data:
            decoded += parser.feed(bytes((byte,)))
        self.assertEqual(decoded, [snapshot()])
        self.assertEqual(parser.frames_decoded, 1)
        self.assertGreater(parser.discarded_bytes, 0)

    def test_crc_failure_resynchronizes(self):
        bad = bytearray(encode_frame(snapshot()))
        bad[32] ^= 1
        parser = StreamParser()
        self.assertEqual(parser.feed(bad + encode_frame(examples()[-1])), [examples()[-1]])
        self.assertGreaterEqual(parser.invalid_frames, 1)

    def test_bad_header_does_not_stall(self):
        headers = (HEADER.pack(b"W3", 2, 1, 96, 0, 0, 0), HEADER.pack(b"W3", 1, 1, 65535, 0, 0, 0))
        for bad in headers:
            parser = StreamParser()
            self.assertEqual(parser.feed(bad + encode_frame(snapshot())), [snapshot()])

    def test_large_input_is_bounded_without_losing_valid_frames(self):
        parser = StreamParser(max_buffer=MAX_FRAME_SIZE)
        encoded = encode_frame(examples()[-1])
        decoded = parser.feed((b"noise" * 10000 + encoded) * 3)
        self.assertEqual(decoded, [examples()[-1]] * 3)
        self.assertLessEqual(parser.buffered_bytes, MAX_FRAME_SIZE)

    def test_optional_w2_and_w3_mixed(self):
        parser = StreamParser(allow_w2=True)
        self.assertEqual(parser.feed(legacy_packet() + encode_frame(snapshot())), [decode_w2(legacy_packet()), snapshot()])
        parser = StreamParser()
        self.assertEqual(parser.feed(legacy_packet() + encode_frame(snapshot())), [snapshot()])

    def test_random_fragmentation(self):
        rng = random.Random(0x532)
        expected = list(examples()) * 10
        data = b"".join(encode_frame(frame) for frame in expected)
        parser = StreamParser()
        actual = []
        while data:
            size = rng.randrange(1, 97)
            actual.extend(parser.feed(data[:size]))
            data = data[size:]
        self.assertEqual(actual, expected)

    def test_reset_clears_partial_on_reconnect(self):
        parser = StreamParser()
        parser.feed(encode_frame(snapshot())[:30])
        parser.reset()
        self.assertEqual(parser.buffered_bytes, 0)
        self.assertEqual(parser.discarded_bytes, 30)
        self.assertEqual(parser.feed(encode_frame(snapshot())), [snapshot()])

    def test_too_small_buffer_rejected(self):
        with self.assertRaises(ValueError):
            StreamParser(max_buffer=MAX_FRAME_SIZE - 1)


CPP_HARNESS = r'''
#include <cstdio>
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif
#include "shared/wii_bridge_protocol.h"
using namespace WiiBridgeProtocol;
int main() {
#ifdef _WIN32
    _setmode(_fileno(stdin), _O_BINARY);
    _setmode(_fileno(stdout), _O_BINARY);
#endif
    uint8_t bytes[MAX_FRAME_SIZE], encoded[MAX_FRAME_SIZE];
    size_t length = std::fread(bytes, 1, sizeof(bytes), stdin);
    FrameView frame;
    if (!DecodeFrame(bytes, length, frame)) return 2;
    size_t count = 0, result = 0;
    switch (frame.header.kind) {
    case SNAPSHOT: {
        SnapshotSlot records[SLOT_COUNT];
        if (!DecodeSnapshot(frame, records, SLOT_COUNT, count)) return 3;
        result = EncodeSnapshot(encoded, sizeof(encoded), frame.header.bootSession,
            frame.header.transportSequence, frame.header.senderTimeMs, records, count); break;
    }
    case DEVICES: {
        DeviceRecord records[SLOT_COUNT];
        if (!DecodeDevices(frame, records, SLOT_COUNT, count)) return 3;
        result = EncodeDevices(encoded, sizeof(encoded), frame.header.bootSession,
            frame.header.transportSequence, frame.header.senderTimeMs, records, count); break;
    }
    case EVENTS: {
        InputEvent records[MAX_PAYLOAD / EVENT_RECORD_SIZE];
        if (!DecodeEvents(frame, records, MAX_PAYLOAD / EVENT_RECORD_SIZE, count)) return 3;
        result = EncodeEvents(encoded, sizeof(encoded), frame.header.bootSession,
            frame.header.transportSequence, frame.header.senderTimeMs, records, count); break;
    }
    case ACK: {
        EventAck records[SLOT_COUNT];
        if (!DecodeAck(frame, records, SLOT_COUNT, count)) return 3;
        result = EncodeAck(encoded, sizeof(encoded), frame.header.bootSession,
            frame.header.transportSequence, frame.header.senderTimeMs, records, count); break;
    }
    }
    if (!result || Crc16(reinterpret_cast<const uint8_t*>("123456789"), 9) != 0x29b1) return 4;
    return std::fwrite(encoded, 1, result, stdout) == result ? 0 : 5;
}
'''


class NativeParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = os.environ.get("CXX") or shutil.which("g++") or shutil.which("clang++")
        if not compiler:
            raise unittest.SkipTest("native g++/clang++ not available; target builds must additionally compile the shared header")
        cls.temporary = tempfile.TemporaryDirectory(prefix="ss8-protocol-")
        cls.addClassCleanup(cls.temporary.cleanup)
        source = Path(cls.temporary.name) / "parity.cpp"
        cls.executable = Path(cls.temporary.name) / ("parity.exe" if os.name == "nt" else "parity")
        source.write_text(CPP_HARNESS, encoding="utf-8")
        subprocess.run([compiler, "-std=c++98", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT), str(source), "-o", str(cls.executable)], check=True, capture_output=True)

    def test_all_kinds_and_crc_match_python(self):
        for frame in examples():
            encoded = encode_frame(frame)
            with self.subTest(kind=frame.kind):
                result = subprocess.run([str(self.executable)], input=encoded, capture_output=True, check=True)
                self.assertEqual(result.stdout, encoded)

    def test_cpp_rejects_bad_crc_and_reserved(self):
        bad = bytearray(encode_frame(snapshot()))
        bad[-1] ^= 1
        self.assertNotEqual(subprocess.run([str(self.executable)], input=bad, capture_output=True).returncode, 0)
        bad = bytearray(encode_frame(snapshot())[:-2])
        bad[40] = 1
        self.assertNotEqual(subprocess.run([str(self.executable)], input=with_crc(bad), capture_output=True).returncode, 0)


if __name__ == "__main__":
    unittest.main()
