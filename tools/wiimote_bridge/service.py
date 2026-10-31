"""Hardware-independent W3 session, identity, freshness and event handling."""
from __future__ import annotations

import time
from dataclasses import dataclass, field, replace

from .mapping import DeviceRegistry, MappingError, normalize_mac
from .protocol import (DEVICE_PRESENT, FLAG_CALIBRATED, FLAG_CONNECTED,
                       FLAG_EVENT_OVERFLOW, FLAG_SAMPLE_VALID, DeviceRecord,
                       EventAck, Frame, InputEvent, MessageKind, SnapshotSlot)

U32_MASK = 0xFFFFFFFF


def newer(sequence: int, previous: int) -> bool:
    return 0 < ((sequence - previous) & U32_MASK) < 0x80000000


def neutral_slot(slot_id: int, *, sample_sequence: int = 0, last_event_sequence: int = 0) -> SnapshotSlot:
    return SnapshotSlot(slot_id, 0, 0, 0, 0, 0, 0xFFFF,
                        sample_sequence, last_event_sequence, 0)


@dataclass
class SlotState:
    snapshot: SnapshotSlot | None = None
    sensor_received_ms: int = 0
    sensor_initial_age_ms: int = 0
    last_received_event: int = 0
    last_consumed_event: int = 0
    pending: list[tuple[int, InputEvent, int]] = field(default_factory=list)
    fault: str | None = None


@dataclass(frozen=True)
class HostView:
    boot_session: int
    slots: tuple[SnapshotSlot, ...]
    events: tuple[InputEvent, ...]
    players: tuple[int, ...]
    faults: tuple[str, ...]


class BridgeService:
    """One ESP32 source. All timing uses an injected host monotonic millisecond clock.

    A snapshot's sample counter advances only for a real radio sample. Repeated
    USB snapshots may lower validity but never refresh an unchanged sample.
    Ordered events remain queued until the guest confirms consuming them.

    Automatic assignment is session-scoped. A caller publishing its views must
    renew the guest host-session whenever routing_revision changes, before the
    next publish, and reject ACKs from the previous host-session. This is the
    existing mailbox reset boundary for replaced devices' lower radio counters.
    """

    def __init__(self, registry: DeviceRegistry, *, timeout_ms: int = 250,
                 max_events_per_slot: int = 64, automatic_assignment: bool = False) -> None:
        if not 20 <= timeout_ms <= 5000 or not 1 <= max_events_per_slot <= 256:
            raise ValueError("Invalid timeout or event queue limit")
        self.registry = registry
        self.automatic_assignment = automatic_assignment
        self.routing_revision = 0
        self._automatic_routes: dict[int, tuple[str, int]] = {}
        self._preferred_players: dict[str, int] = {}
        self.timeout_ms = timeout_ms
        self.max_events_per_slot = max_events_per_slot
        self.boot_session: int | None = None
        self.transport_sequence: int | None = None
        self.devices: dict[int, str] = {}
        self.slots = [SlotState() for _ in range(4)]
        self.retired_boot_sessions: list[int] = []
        self.last_packet_ms: int | None = None
        self.receipt_order = 0
        self.counters = {name: 0 for name in ("accepted_frames", "stale_frames", "session_changes",
                                             "duplicate_events", "event_gaps", "queue_overflows",
                                             "stale_events", "unmapped_events")}

    @staticmethod
    def _now() -> int:
        return time.monotonic_ns() // 1_000_000

    @property
    def assignments(self) -> dict[int, int]:
        """Current source-to-player routes; automatic routes require a connection.

        A DEVICES table also contains disconnected NVS reservations. Those must
        never consume a player slot merely because an old address was remembered.
        """
        if self.automatic_assignment:
            return {source: player for source, (_, player) in self._automatic_routes.items()}
        return {source: player for source, identity in self.devices.items()
                if (player := self.registry.player_for(identity)) is not None}

    def _routing_changed(self) -> None:
        """A routing revision requires a new guest host-session before publishing.

        All four guest filters/ACK baselines reset at that boundary. Drop queued
        actions explicitly and ACK them to the radio rather than replaying them
        with another device's identity or accepting a previous guest session ACK.
        """
        self.routing_revision += 1
        for state in self.slots:
            baseline = state.last_received_event
            if state.snapshot and newer(state.snapshot.last_event_sequence, baseline):
                baseline = state.snapshot.last_event_sequence
            state.pending.clear()
            state.last_received_event = state.last_consumed_event = baseline
            if state.snapshot:
                state.snapshot = replace(state.snapshot, last_event_sequence=baseline)

    def _sync_automatic_routes(self) -> None:
        if not self.automatic_assignment:
            return
        changed = False
        for source, (identity, _) in list(self._automatic_routes.items()):
            sample = self.slots[source].snapshot
            if (self.devices.get(source) != identity or sample is None
                    or not sample.flags & FLAG_CONNECTED):
                del self._automatic_routes[source]
                changed = True
        occupied = {player for _, player in self._automatic_routes.values()}
        for source, state in enumerate(self.slots):
            identity = self.devices.get(source)
            if (source in self._automatic_routes or identity is None or state.snapshot is None
                    or not state.snapshot.flags & FLAG_CONNECTED):
                continue
            preferred = self._preferred_players.get(identity)
            player = preferred if preferred is not None and preferred not in occupied else next(
                (candidate for candidate in range(5, 9) if candidate not in occupied), None)
            if player is None:
                continue
            self._automatic_routes[source] = (identity, player)
            self._preferred_players.pop(identity, None)
            self._preferred_players[identity] = player
            if len(self._preferred_players) > 64:
                del self._preferred_players[next(iter(self._preferred_players))]
            occupied.add(player)
            changed = True
        if changed:
            self._routing_changed()

    def _session(self, frame: Frame) -> bool:
        if frame.boot_session == 0 or frame.boot_session in self.retired_boot_sessions:
            return False
        if self.boot_session != frame.boot_session:
            if self.boot_session is not None:
                self.retired_boot_sessions.append(self.boot_session)
                self.retired_boot_sessions = self.retired_boot_sessions[-16:]
            self.boot_session = frame.boot_session
            self.transport_sequence = None
            self.devices.clear()
            self.slots = [SlotState() for _ in range(4)]
            if self.automatic_assignment:
                self._automatic_routes.clear()
                self._preferred_players.clear()
                self._routing_changed()
            self.counters["session_changes"] += 1
        return True

    def ingest(self, frame: Frame, *, now_ms: int | None = None) -> bool:
        now = self._now() if now_ms is None else now_ms
        if not self._session(frame):
            self.counters["stale_frames"] += 1
            return False
        if self.transport_sequence is not None and not newer(frame.transport_sequence, self.transport_sequence):
            self.counters["stale_frames"] += 1
            return False
        self.transport_sequence = frame.transport_sequence
        self.last_packet_ms = now
        self.counters["accepted_frames"] += 1
        if frame.kind == MessageKind.DEVICES:
            identities: dict[int, str] = {}
            for record in frame.records:
                assert isinstance(record, DeviceRecord)
                if not record.flags & DEVICE_PRESENT:
                    continue
                try:
                    address = normalize_mac(record.mac)
                except MappingError:
                    continue
                if address in identities.values():
                    # A repeated address is ambiguous; route none of this table.
                    self.devices.clear()
                    self._sync_automatic_routes()
                    for state in self.slots:
                        state.fault = "duplicate device identity"
                    return False
                identities[record.slot_id] = address
            for source in range(4):
                if identities.get(source) != self.devices.get(source):
                    self.slots[source] = SlotState()
            self.devices = identities
            self._sync_automatic_routes()
        elif frame.kind == MessageKind.SNAPSHOT:
            for record in frame.records:
                assert isinstance(record, SnapshotSlot)
                self._snapshot(record, now)
            self._sync_automatic_routes()
        elif frame.kind == MessageKind.EVENTS:
            for record in frame.records:
                assert isinstance(record, InputEvent)
                self._event(record, frame.sender_time_ms, now)
        return True

    def _snapshot(self, record: SnapshotSlot, now: int) -> None:
        state = self.slots[record.slot_id]
        previous = state.snapshot
        disconnected = not record.flags & FLAG_CONNECTED
        if (self.automatic_assignment and previous is not None
                and not previous.flags & FLAG_CONNECTED and not disconnected):
            # Reconnection starts fresh firmware counters even for the same MAC.
            # The route's new guest host-session establishes the matching baseline.
            self.slots[record.slot_id] = state = SlotState()
            previous = None
        first = previous is None
        if disconnected or first:
            # Startup/disconnect is an explicit neutral synchronization boundary.
            # Old queued events are discarded, not replayed into a new binding.
            state.pending.clear()
            state.last_received_event = record.last_event_sequence
            state.last_consumed_event = record.last_event_sequence
            state.fault = None
        if record.flags & FLAG_EVENT_OVERFLOW:
            state.pending.clear()
            state.last_received_event = record.last_event_sequence
            state.last_consumed_event = record.last_event_sequence
            state.fault = "firmware event queue overflow; release all buttons to resynchronize"
        elif state.fault and record.flags & FLAG_CONNECTED:
            # Fault recovery is an explicit neutral discard boundary. Tell the
            # source which old events were discarded; never play them later.
            state.pending.clear()
            state.last_received_event = record.last_event_sequence
            state.last_consumed_event = record.last_event_sequence
            if (record.buttons == 0 and record.sample_age_ms < self.timeout_ms
                    and record.flags & FLAG_SAMPLE_VALID
                    and (previous is None or newer(record.sample_sequence, previous.sample_sequence))):
                state.fault = None
        if previous is not None and not disconnected:
            if record.sample_sequence != previous.sample_sequence and not newer(record.sample_sequence, previous.sample_sequence):
                return
        if first or previous is None or record.sample_sequence != previous.sample_sequence:
            state.sensor_received_ms = now
            state.sensor_initial_age_ms = record.sample_age_ms
        else:
            # A source is allowed to report a larger age; never make it younger.
            projected_age = state.sensor_initial_age_ms + max(0, now - state.sensor_received_ms)
            if record.sample_age_ms > projected_age:
                state.sensor_initial_age_ms = record.sample_age_ms
                state.sensor_received_ms = now
        state.snapshot = record

    def _event(self, event: InputEvent, sender_time_ms: int, now: int) -> None:
        state = self.slots[event.slot_id]
        snapshot = state.snapshot
        if snapshot is None or not snapshot.flags & FLAG_CONNECTED or state.fault:
            return
        if not newer(event.event_sequence, state.last_received_event):
            self.counters["duplicate_events"] += 1
            return
        if event.event_sequence != ((state.last_received_event + 1) & U32_MASK):
            state.fault = "event sequence gap; release all buttons to resynchronize"
            state.pending.clear()
            self.counters["event_gaps"] += 1
            return
        age = (sender_time_ms - event.sample_time_ms) & U32_MASK
        if age >= self.timeout_ms:
            # Never issue a delayed item/trick. Discard and ACK this old event
            # at a neutral boundary; this is not a gameplay-consumption claim.
            state.pending.clear()
            state.last_received_event = event.event_sequence
            state.last_consumed_event = event.event_sequence
            state.fault = "stale event; release all buttons to resynchronize"
            self.counters["stale_events"] += 1
            return
        if len(state.pending) >= self.max_events_per_slot:
            state.pending.clear()
            state.fault = "host event queue overflow; release all buttons to resynchronize"
            self.counters["queue_overflows"] += 1
            return
        self.receipt_order += 1
        state.pending.append((self.receipt_order, event, now - age))
        state.last_received_event = event.event_sequence

    def view(self, *, now_ms: int | None = None, max_events: int = 32) -> HostView:
        if not 0 <= max_events <= 32:
            raise ValueError("Guest mailbox allows at most 32 pending events")
        now = self._now() if now_ms is None else now_ms
        output = [neutral_slot(i) for i in range(4)]
        events: list[tuple[int, InputEvent]] = []
        players: list[int] = []
        faults: list[str] = []
        assignments = self.assignments
        for source, state in enumerate(self.slots):
            player = assignments.get(source)
            if player is None:
                continue
            logical = player - 5
            record = state.snapshot
            if state.pending and now - state.pending[0][2] >= self.timeout_ms:
                state.pending.clear()
                state.last_consumed_event = state.last_received_event
                state.fault = "guest event consumption stalled; release all buttons to resynchronize"
                self.counters["stale_events"] += 1
            if state.fault:
                faults.append(f"P{player}: {state.fault}")
            if record is None:
                continue
            age = min(0xFFFF, state.sensor_initial_age_ms + max(0, now - state.sensor_received_ms))
            required = FLAG_CONNECTED | FLAG_SAMPLE_VALID | FLAG_CALIBRATED
            fresh = ((record.flags & required) == required and age < self.timeout_ms and not state.fault)
            if fresh:
                output[logical] = replace(record, slot_id=logical, sample_age_ms=age)
                players.append(player)
                events.extend((order, replace(event, slot_id=logical)) for order, event, _ in state.pending)
            else:
                output[logical] = neutral_slot(logical, sample_sequence=record.sample_sequence,
                                               last_event_sequence=state.last_consumed_event)
        events.sort(key=lambda item: item[0])
        return HostView(self.boot_session or 0, tuple(output), tuple(event for _, event in events[:max_events]),
                        tuple(players), tuple(faults))

    def acknowledge_guest(self, acknowledged: tuple[int, ...] | list[int]) -> None:
        if len(acknowledged) != 4:
            raise ValueError("Guest ACK must contain four logical slots")
        for source, player in self.assignments.items():
            sequence = acknowledged[player - 5]
            state = self.slots[source]
            if sequence == state.last_consumed_event:
                continue
            # Do not trust a guest ACK for an event never placed in our queue.
            indices = [i for i, (_, event, _) in enumerate(state.pending)
                       if event.event_sequence == sequence]
            if indices:
                del state.pending[:indices[0] + 1]
                state.last_consumed_event = sequence

    def ack_records(self) -> tuple[EventAck, ...]:
        return tuple(EventAck(i, state.last_consumed_event) for i, state in enumerate(self.slots))

    def drain_diagnostic_events(self) -> None:
        """Explicit diagnostic sink: events were inspected/recorded, not applied in a game."""
        for state in self.slots:
            if state.pending:
                state.last_consumed_event = state.pending[-1][1].event_sequence
                state.pending.clear()
