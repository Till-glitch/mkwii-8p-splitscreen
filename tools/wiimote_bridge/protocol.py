"""Strict, dependency-free codecs for Wii bridge W3 and legacy W2 captures.

This module validates wire data; session ordering, event acknowledgement and
freshness decisions belong to the transport service. Snapshot event flags are
diagnostic, never another delivery path for an event.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import struct
from typing import Union

MAGIC = b"W3"
VERSION = 1
SLOT_COUNT = 4
MAX_PAYLOAD = 512
HEADER = struct.Struct(">2sBBHIII")
HEADER_SIZE = HEADER.size
CRC_SIZE = 2
MAX_FRAME_SIZE = HEADER_SIZE + MAX_PAYLOAD + CRC_SIZE
SNAPSHOT_RECORD = struct.Struct(">BBHhhhHIIHH")
DEVICE_RECORD = struct.Struct(">BB6s")
EVENT_RECORD = struct.Struct(">BBHIII")
ACK_RECORD = struct.Struct(">BBHI")
LEGACY_SIZE = 32

FLAG_CONNECTED = 1
FLAG_CALIBRATED = 2
FLAG_SAMPLE_VALID = 4
FLAG_EVENT_OVERFLOW = 8
SNAPSHOT_FLAGS = 0x0F
EVENT_FLAG_TRICK = 1
DEVICE_PRESENT = 1


class MessageKind(IntEnum):
    SNAPSHOT = 1
    DEVICES = 2
    EVENTS = 3
    ACK = 4


class EventKind(IntEnum):
    BUTTONS = 1
    TRICK = 2


class ProtocolError(ValueError):
    """The complete frame or record violates the wire contract."""


@dataclass(frozen=True)
class SnapshotSlot:
    slot_id: int
    flags: int
    buttons: int
    accel_x: int
    accel_y: int
    accel_z: int
    sample_age_ms: int
    sample_sequence: int
    last_event_sequence: int
    event_flags: int = 0


@dataclass(frozen=True)
class DeviceRecord:
    slot_id: int
    flags: int
    mac: bytes


@dataclass(frozen=True)
class InputEvent:
    slot_id: int
    event_kind: EventKind
    value: int
    event_sequence: int
    sample_sequence: int
    sample_time_ms: int


@dataclass(frozen=True)
class EventAck:
    slot_id: int
    acked_event_sequence: int


Record = Union[SnapshotSlot, DeviceRecord, InputEvent, EventAck]


@dataclass(frozen=True)
class Frame:
    kind: MessageKind
    boot_session: int
    transport_sequence: int
    sender_time_ms: int
    records: tuple[Record, ...]


@dataclass(frozen=True)
class LegacySlot:
    slot_id: int
    connected: bool
    calibrated: bool
    buttons: int
    accel_x: int
    accel_y: int
    accel_z: int
    sequence: int
    trick: bool


@dataclass(frozen=True)
class LegacySnapshot:
    connected_mask: int
    slots: tuple[LegacySlot, ...]


def crc16(data: bytes | bytearray | memoryview) -> int:
    """CRC-16/CCITT-FALSE: poly 1021, init FFFF, no reflection/xorout."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ (0x1021 if crc & 0x8000 else 0)) & 0xFFFF
    return crc


def _integer(value: int, minimum: int, maximum: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ProtocolError(f"{label} must be an integer in {minimum}..{maximum}")
    return value


def _slot(slot_id: int) -> int:
    return _integer(slot_id, 0, SLOT_COUNT - 1, "slot_id")


def _kind(value: int) -> MessageKind:
    _integer(value, 1, 255, "kind")
    try:
        return MessageKind(value)
    except ValueError as error:
        raise ProtocolError(f"unknown message kind {value}") from error


def _event_kind(value: int) -> EventKind:
    _integer(value, 1, 255, "event_kind")
    try:
        return EventKind(value)
    except ValueError as error:
        raise ProtocolError(f"unknown event kind {value}") from error


def _payload_shape(kind: MessageKind, length: int) -> None:
    if not 0 <= length <= MAX_PAYLOAD:
        raise ProtocolError("payload exceeds maximum length")
    if kind == MessageKind.SNAPSHOT and length != SLOT_COUNT * SNAPSHOT_RECORD.size:
        raise ProtocolError("snapshot requires four 24-byte slots")
    if kind == MessageKind.DEVICES and length != SLOT_COUNT * DEVICE_RECORD.size:
        raise ProtocolError("devices requires four 8-byte records")
    if kind == MessageKind.EVENTS and (not length or length % EVENT_RECORD.size):
        raise ProtocolError("events requires one or more 16-byte records")
    if kind == MessageKind.ACK and (not length or length % ACK_RECORD.size or length > SLOT_COUNT * ACK_RECORD.size):
        raise ProtocolError("ack requires one to four 8-byte records")


def _unique_slots(records: tuple[Record, ...], *, all_slots: bool) -> None:
    slots = [_slot(record.slot_id) for record in records]
    if len(slots) != len(set(slots)):
        raise ProtocolError("duplicate slot_id")
    if all_slots and set(slots) != set(range(SLOT_COUNT)):
        raise ProtocolError("all four slots must be represented")


def _encode_payload(kind: MessageKind, records: tuple[Record, ...]) -> bytes:
    expected_type = {
        MessageKind.SNAPSHOT: SnapshotSlot,
        MessageKind.DEVICES: DeviceRecord,
        MessageKind.EVENTS: InputEvent,
        MessageKind.ACK: EventAck,
    }[kind]
    if not isinstance(records, (tuple, list)) or any(not isinstance(record, expected_type) for record in records):
        raise ProtocolError(f"{kind.name.lower()} requires {expected_type.__name__} records")
    chunks = []
    if kind in (MessageKind.SNAPSHOT, MessageKind.DEVICES):
        if len(records) != SLOT_COUNT:
            raise ProtocolError("snapshot/devices must contain four records")
        _unique_slots(records, all_slots=True)
    elif kind == MessageKind.ACK:
        if not 1 <= len(records) <= SLOT_COUNT:
            raise ProtocolError("ack must contain one to four records")
        _unique_slots(records, all_slots=False)
    elif not 1 <= len(records) <= MAX_PAYLOAD // EVENT_RECORD.size:
        raise ProtocolError("events must contain one to 32 records")
    for record in records:
        _slot(record.slot_id)
        if kind == MessageKind.SNAPSHOT:
            if not isinstance(record, SnapshotSlot):
                raise ProtocolError("snapshot requires SnapshotSlot records")
            flags = _integer(record.flags, 0, SNAPSHOT_FLAGS, "flags")
            event_flags = _integer(record.event_flags, 0, EVENT_FLAG_TRICK, "event_flags")
            values = (
                record.slot_id, flags, _integer(record.buttons, 0, 0xFFFF, "buttons"),
                _integer(record.accel_x, -512, 511, "accel_x"),
                _integer(record.accel_y, -512, 511, "accel_y"),
                _integer(record.accel_z, -512, 511, "accel_z"),
                _integer(record.sample_age_ms, 0, 0xFFFF, "sample_age_ms"),
                _integer(record.sample_sequence, 0, 0xFFFFFFFF, "sample_sequence"),
                _integer(record.last_event_sequence, 0, 0xFFFFFFFF, "last_event_sequence"),
                event_flags, 0,
            )
            chunks.append(SNAPSHOT_RECORD.pack(*values))
        elif kind == MessageKind.DEVICES:
            if not isinstance(record, DeviceRecord):
                raise ProtocolError("devices requires DeviceRecord records")
            flags = _integer(record.flags, 0, DEVICE_PRESENT, "device flags")
            if not isinstance(record.mac, bytes) or len(record.mac) != 6:
                raise ProtocolError("mac must contain exactly six bytes")
            chunks.append(DEVICE_RECORD.pack(record.slot_id, flags, record.mac))
        elif kind == MessageKind.EVENTS:
            if not isinstance(record, InputEvent):
                raise ProtocolError("events requires InputEvent records")
            chunks.append(EVENT_RECORD.pack(
                record.slot_id, _event_kind(record.event_kind),
                _integer(record.value, 0, 0xFFFF, "event value"),
                _integer(record.event_sequence, 0, 0xFFFFFFFF, "event_sequence"),
                _integer(record.sample_sequence, 0, 0xFFFFFFFF, "sample_sequence"),
                _integer(record.sample_time_ms, 0, 0xFFFFFFFF, "sample_time_ms"),
            ))
        else:
            if not isinstance(record, EventAck):
                raise ProtocolError("ack requires EventAck records")
            chunks.append(ACK_RECORD.pack(
                record.slot_id, 0, 0,
                _integer(record.acked_event_sequence, 0, 0xFFFFFFFF, "acked_event_sequence"),
            ))
    payload = b"".join(chunks)
    _payload_shape(kind, len(payload))
    return payload


def encode_frame(frame: Frame) -> bytes:
    kind = _kind(frame.kind)
    payload = _encode_payload(kind, frame.records)
    header = HEADER.pack(
        MAGIC, VERSION, kind, len(payload),
        _integer(frame.boot_session, 0, 0xFFFFFFFF, "boot_session"),
        _integer(frame.transport_sequence, 0, 0xFFFFFFFF, "transport_sequence"),
        _integer(frame.sender_time_ms, 0, 0xFFFFFFFF, "sender_time_ms"),
    )
    body = header + payload
    return body + struct.pack(">H", crc16(body))


def decode_frame(data: bytes | bytearray | memoryview) -> Frame:
    if len(data) < HEADER_SIZE + CRC_SIZE:
        raise ProtocolError("truncated W3 frame")
    magic, version, raw_kind, length, session, sequence, time_ms = HEADER.unpack_from(data)
    if magic != MAGIC:
        raise ProtocolError("invalid W3 magic")
    if version != VERSION:
        raise ProtocolError(f"unsupported W3 version {version}")
    kind = _kind(raw_kind)
    _payload_shape(kind, length)
    if len(data) != HEADER_SIZE + length + CRC_SIZE:
        raise ProtocolError("W3 length mismatch")
    if crc16(memoryview(data)[:-CRC_SIZE]) != struct.unpack_from(">H", data, len(data) - CRC_SIZE)[0]:
        raise ProtocolError("invalid W3 CRC")
    payload = memoryview(data)[HEADER_SIZE:-CRC_SIZE]
    records: list[Record] = []
    if kind == MessageKind.SNAPSHOT:
        for values in SNAPSHOT_RECORD.iter_unpack(payload):
            if values[-1] != 0:
                raise ProtocolError("snapshot reserved field is nonzero")
            records.append(SnapshotSlot(*values[:-1]))
    elif kind == MessageKind.DEVICES:
        records.extend(DeviceRecord(*values) for values in DEVICE_RECORD.iter_unpack(payload))
    elif kind == MessageKind.EVENTS:
        records.extend(InputEvent(values[0], _event_kind(values[1]), *values[2:]) for values in EVENT_RECORD.iter_unpack(payload))
    else:
        for slot_id, reserved1, reserved2, acked in ACK_RECORD.iter_unpack(payload):
            if reserved1 or reserved2:
                raise ProtocolError("ack reserved fields are nonzero")
            records.append(EventAck(slot_id, acked))
    result = Frame(kind, session, sequence, time_ms, tuple(records))
    # Reuse the same semantic validation for both directions of the contract.
    _encode_payload(kind, result.records)
    return result


def decode_w2(data: bytes | bytearray | memoryview) -> LegacySnapshot:
    if len(data) != LEGACY_SIZE or data[:2] != b"W2":
        raise ProtocolError("W2 requires exactly 32 bytes and W2 magic")
    mask = data[2]
    if mask & ~0x0F:
        raise ProtocolError("invalid W2 connected mask")
    checksum = mask
    for byte in data[4:]:
        checksum ^= byte
    if checksum != data[3]:
        raise ProtocolError("invalid W2 checksum")
    slots = []
    for slot_id in range(SLOT_COUNT):
        offset = 4 + slot_id * 7
        packed = data[offset + 5]
        axes = []
        for axis in range(3):
            value = data[offset + 2 + axis] | (((packed >> (axis * 2)) & 3) << 8)
            axes.append(value - 1024 if value & 512 else value)
        slots.append(LegacySlot(
            slot_id, bool(mask & (1 << slot_id)), bool(packed & 128),
            (data[offset] << 8) | data[offset + 1], *axes,
            data[offset + 6], bool(packed & 64),
        ))
    return LegacySnapshot(mask, tuple(slots))


class StreamParser:
    """Recover valid frames from noisy/chunked serial bytes with bounded storage.

    Maximum storage is ``max_buffer`` regardless of feed size. A valid-looking
    incomplete header may delay recovery until its bounded declared length has
    arrived; UART freshness/timeouts remain the caller's responsibility.
    """

    def __init__(self, *, allow_w2: bool = False, max_buffer: int = 4096):
        if max_buffer < MAX_FRAME_SIZE:
            raise ValueError(f"max_buffer must be at least {MAX_FRAME_SIZE}")
        self.allow_w2 = allow_w2
        self.max_buffer = max_buffer
        self._buffer = bytearray()
        self.discarded_bytes = 0
        self.invalid_frames = 0
        self.frames_decoded = 0

    @property
    def buffered_bytes(self) -> int:
        return len(self._buffer)

    def reset(self) -> None:
        """Discard partial framing on a physical reconnect; counters survive."""
        self.discarded_bytes += len(self._buffer)
        self._buffer.clear()

    def _discard(self, count: int) -> None:
        self.discarded_bytes += count
        del self._buffer[:count]

    def _drain(self) -> list[Frame | LegacySnapshot]:
        frames: list[Frame | LegacySnapshot] = []
        while self._buffer:
            w3 = self._buffer.find(MAGIC)
            w2 = self._buffer.find(b"W2") if self.allow_w2 else -1
            starts = [offset for offset in (w3, w2) if offset >= 0]
            if not starts:
                self._discard(len(self._buffer) - (1 if self._buffer[-1] == ord("W") else 0))
                break
            start = min(starts)
            if start:
                self._discard(start)
            if self._buffer[:2] == b"W2":
                length = LEGACY_SIZE
            else:
                if len(self._buffer) < HEADER_SIZE:
                    break
                _, version, raw_kind, payload_length, _, _, _ = HEADER.unpack_from(self._buffer)
                try:
                    if version != VERSION:
                        raise ProtocolError("unsupported W3 version")
                    _payload_shape(_kind(raw_kind), payload_length)
                except ProtocolError:
                    self.invalid_frames += 1
                    self._discard(1)
                    continue
                length = HEADER_SIZE + payload_length + CRC_SIZE
            if len(self._buffer) < length:
                break
            candidate = bytes(self._buffer[:length])
            try:
                frame = decode_w2(candidate) if candidate[:2] == b"W2" else decode_frame(candidate)
            except ProtocolError:
                self.invalid_frames += 1
                self._discard(1)
                continue
            del self._buffer[:length]
            frames.append(frame)
            self.frames_decoded += 1
        return frames

    def feed(self, data: bytes | bytearray | memoryview) -> list[Frame | LegacySnapshot]:
        frames: list[Frame | LegacySnapshot] = []
        view = memoryview(data)
        position = 0
        while position < len(view):
            room = self.max_buffer - len(self._buffer)
            if room == 0:
                # A declared frame is at most MAX_FRAME_SIZE; therefore a full
                # buffer cannot be a valid incomplete frame after _drain().
                self._discard(1)
                room = 1
            count = min(room, len(view) - position)
            self._buffer.extend(view[position:position + count])
            position += count
            frames.extend(self._drain())
        return frames


# Names retained for callers that describe these as records/decoders.
EventRecord = InputEvent
AckRecord = EventAck
StreamDecoder = StreamParser
crc16_ccitt_false = crc16
