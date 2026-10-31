"""Versioned guest mailbox v1. No guessed game or injection addresses.

All byte offsets are the explicit SS8WBRG1 ABI, not native game structures.
The only write locations are the input buffer validated from its descriptor.
"""
from __future__ import annotations

import json
import secrets
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .protocol import InputEvent, SnapshotSlot
from .service import HostView

MAGIC = b"SS8WBRG1"
ABI_VERSION = 1
DESCRIPTOR_SIZE = 64
INPUT_SIZE = 640
STATUS_SIZE = 96
SLOT_STRUCT = struct.Struct(">BBHhhhHIIHH")
EVENT_STRUCT = struct.Struct(">BBHIII")
DESCRIPTOR_STRUCT = struct.Struct(">8sHHI16sIIIIIHHII")
ALLOWED_MEMORY = ((0x80000000, 0x81800000), (0x90000000, 0x94000000))


class MailboxError(RuntimeError):
    pass


class MailboxBusyError(MailboxError):
    pass


class MemoryBackend(Protocol):
    pid: int

    def read(self, address: int, size: int) -> bytes: ...
    def write(self, address: int, data: bytes) -> None: ...
    def ensure_target(self) -> None: ...


def valid_range(address: int, size: int) -> bool:
    return size > 0 and address % 4 == 0 and any(start <= address and address + size <= end
                                                for start, end in ALLOWED_MEMORY)


def overlaps(first: int, first_size: int, second: int, second_size: int) -> bool:
    return first < second + second_size and second < first + first_size


def checksum(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


@dataclass(frozen=True)
class BuildManifest:
    build_id: bytes
    game_id: str

    @classmethod
    def load(cls, path: Path) -> BuildManifest:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            build = bytes.fromhex(value["build_id"])
            game = value.get("game_id", "RMCP01")
            if len(build) != 16 or game != "RMCP01" or value.get("descriptor_abi", 1) != 1:
                raise ValueError("Unsupported build/game/ABI")
        except (ValueError, KeyError, TypeError, OSError) as exc:
            raise MailboxError(f"Invalid bridge build manifest {path}: {exc}") from exc
        return cls(build, game)


@dataclass(frozen=True)
class Descriptor:
    capabilities: int
    build_id: bytes
    guest_session: int
    input_address: int
    status_address: int

    @classmethod
    def decode(cls, data: bytes, expected_build: bytes, address: int) -> Descriptor:
        if len(data) != DESCRIPTOR_SIZE or not valid_range(address, DESCRIPTOR_SIZE):
            raise MailboxError("Descriptor has invalid length or address")
        (magic, abi, length, capabilities, build, guest_session, input_address,
         input_bytes, status_address, status_bytes, slots, reserved, ready, crc) = DESCRIPTOR_STRUCT.unpack(data)
        if magic != MAGIC or abi != ABI_VERSION or length != DESCRIPTOR_SIZE:
            raise MailboxError("Guest does not expose the supported SS8WBRG1 ABI")
        if checksum(data[:60]) != crc or build != expected_build:
            raise MailboxError("Descriptor CRC/build does not match this build manifest")
        if not guest_session or ready != 1 or slots != 4 or reserved != 0:
            raise MailboxError("Guest descriptor is not ready or has invalid session/slots")
        if input_bytes != INPUT_SIZE or status_bytes != STATUS_SIZE:
            raise MailboxError("Unexpected guest buffer sizes")
        if not valid_range(input_address, INPUT_SIZE) or not valid_range(status_address, STATUS_SIZE):
            raise MailboxError("Guest buffer is outside supported Wii RAM")
        if (overlaps(address, DESCRIPTOR_SIZE, input_address, INPUT_SIZE)
                or overlaps(address, DESCRIPTOR_SIZE, status_address, STATUS_SIZE)
                or overlaps(input_address, INPUT_SIZE, status_address, STATUS_SIZE)):
            raise MailboxError("Guest descriptor/input/status buffers overlap")
        return cls(capabilities, build, guest_session, input_address, status_address)


@dataclass(frozen=True)
class GuestStatus:
    generation: int
    guest_session: int
    guest_tick: int
    host_session: int
    publish_sequence: int
    source_session: int
    flags: int
    last_error: int
    acknowledged_events: tuple[int, ...]
    applied_samples: tuple[int, ...]
    bound_player_mask: int
    input_age_ticks: int
    accepted_count: int
    rejected_count: int

    @classmethod
    def decode(cls, data: bytes, *, guest_session: int) -> GuestStatus:
        if len(data) != STATUS_SIZE:
            raise MailboxError("Incomplete guest status")
        words = struct.unpack(">24I", data)
        if words[0] == 0 or words[0] & 1 or words[1] != guest_session:
            raise MailboxError("Guest status is incomplete or belongs to another session")
        if checksum(data[4:92]) != words[23] or any(words[20:23]):
            raise MailboxError("Invalid guest status CRC/reserved fields")
        return cls(*words[:8], tuple(words[8:12]), tuple(words[12:16]), *words[16:20])


def encode_input(view: HostView, *, generation: int, guest_session: int,
                 host_session: int, publish_sequence: int, host_elapsed_ms: int) -> bytes:
    if generation == 0 or generation & 1 or not guest_session or not host_session:
        raise MailboxError("Input commit requires even generation and nonzero sessions")
    if len(view.slots) != 4 or len(view.events) > 32:
        raise MailboxError("Guest input requires four slots and at most 32 events")
    data = bytearray(INPUT_SIZE)
    struct.pack_into(">6IHHI", data, 0, generation & 0xFFFFFFFF, guest_session,
                     host_session, publish_sequence & 0xFFFFFFFF, view.boot_session,
                     host_elapsed_ms & 0xFFFFFFFF, len(view.events), 4, 0)
    for index, slot in enumerate(view.slots):
        if slot.slot_id != index:
            raise MailboxError("Guest snapshots must be in logical player-slot order")
        SLOT_STRUCT.pack_into(data, 32 + index * 24, slot.slot_id, slot.flags, slot.buttons,
                              slot.accel_x, slot.accel_y, slot.accel_z, slot.sample_age_ms,
                              slot.sample_sequence, slot.last_event_sequence, slot.event_flags, 0)
    for index, event in enumerate(view.events):
        EVENT_STRUCT.pack_into(data, 128 + index * 16, event.slot_id, event.event_kind,
                               event.value, event.event_sequence, event.sample_sequence, event.sample_time_ms)
    struct.pack_into(">I", data, 28, checksum(data[4:28] + data[32:]))
    return bytes(data)


class GuestMailbox:
    def __init__(self, backend: MemoryBackend, descriptor_address: int,
                 manifest: BuildManifest, *, host_session: int | None = None) -> None:
        if backend.pid <= 0:
            raise MailboxError("A selected Dolphin PID is required")
        self.backend = backend
        self.descriptor_address = descriptor_address
        self.manifest = manifest
        self.host_session = (secrets.randbits(32) or 1) if host_session is None else host_session
        if not 0 < self.host_session <= 0xFFFFFFFF:
            raise MailboxError("Host session must be a nonzero u32")
        self.generation = 0
        self.publish_sequence = 0
        self.descriptor = self._verify_descriptor()
        authorize = getattr(self.backend, "authorize_write_range", None)
        if authorize is not None:
            authorize(self.descriptor.input_address, INPUT_SIZE)

    def _verify_descriptor(self) -> Descriptor:
        self.backend.ensure_target()
        if self.backend.read(0x80000000, 6) != self.manifest.game_id.encode("ascii"):
            raise MailboxError("Selected Dolphin is not running the supported game")
        first = self.backend.read(self.descriptor_address, DESCRIPTOR_SIZE)
        if first != self.backend.read(self.descriptor_address, DESCRIPTOR_SIZE):
            raise MailboxError("Guest descriptor changed while reading")
        return Descriptor.decode(first, self.manifest.build_id, self.descriptor_address)

    def read_status(self) -> GuestStatus:
        current = self._verify_descriptor()
        if current != self.descriptor:
            raise MailboxError("Guest restarted or descriptor changed; reconnect explicitly")
        for _ in range(2):
            data = self.backend.read(self.descriptor.status_address, STATUS_SIZE)
            generation = self.backend.read(self.descriptor.status_address, 4)
            if len(data) != STATUS_SIZE or len(generation) != 4:
                raise MailboxError("Incomplete guest status read")
            if data[:4] != generation or struct.unpack(">I", generation)[0] & 1 or generation == bytes(4):
                continue
            return GuestStatus.decode(data, guest_session=self.descriptor.guest_session)
        raise MailboxBusyError("Guest status is busy; no unbounded read retry")

    def renew_host_session(self) -> None:
        """Start a neutral guest boundary after a controller binding changes.

        Raw device counters may restart or move to another logical slot. A new
        host session makes the receiver discard old actions and ACKs before
        accepting those counters, without changing the transport boot session.
        Generation stays monotonic so every commit remains observable.
        """
        if self._verify_descriptor() != self.descriptor:
            raise MailboxError("Guest restarted or descriptor changed; reconnect explicitly")
        previous = self.host_session
        self.host_session = secrets.randbits(32) or 1
        if self.host_session == previous:
            self.host_session = (previous % 0xFFFFFFFF) + 1
        self.publish_sequence = 0

    def publish(self, view: HostView, *, host_elapsed_ms: int) -> int:
        current = self._verify_descriptor()
        if current != self.descriptor:
            raise MailboxError("Guest restarted or descriptor changed; reconnect explicitly")
        self.generation = ((self.generation + 2) & 0xFFFFFFFE) or 2
        self.publish_sequence = (self.publish_sequence + 1) & 0xFFFFFFFF
        data = encode_input(view, generation=self.generation,
                            guest_session=self.descriptor.guest_session, host_session=self.host_session,
                            publish_sequence=self.publish_sequence, host_elapsed_ms=host_elapsed_ms)
        address = self.descriptor.input_address
        self.backend.write(address, struct.pack(">I", self.generation | 1))
        self.backend.write(address + 4, data[4:])
        self.backend.write(address, data[:4])
        return self.publish_sequence
