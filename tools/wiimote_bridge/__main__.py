"""Command line entry point; offline modes never import serial or memory APIs."""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
from pathlib import Path

from .mailbox import BuildManifest, GuestMailbox, MailboxBusyError, MailboxError
from .mapping import DeviceRegistry, MappingError
from .ports import PortSelectionError, available_ports, choose_port
from .protocol import Frame, LegacySnapshot, MessageKind, StreamParser, encode_frame
from .recording import RecordingError, RecordingWriter, read_recording
from .service import BridgeService


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ESP32 Wii bridge: diagnostics, recording and explicit guest attachment")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--ports", action="store_true", help="List serial ports; no port is opened")
    modes.add_argument("--diagnose", action="store_true", help="Read/ACK ESP32 input in a diagnostic sink; never attach to Dolphin")
    modes.add_argument("--replay", type=Path, help="Read a JSONL capture offline; never attach to Dolphin")
    modes.add_argument("--attach", action="store_true", help="Publish to an explicitly verified diagnostic guest mailbox")
    parser.add_argument("--port", help="Explicit serial port (required if detection is ambiguous)")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--config", type=Path, default=Path("build/wiimote-bridge/config.json"))
    parser.add_argument("--assign", action="append", default=[], metavar="MAC=PLAYER",
                        help="Explicitly reserve a device for P5..P8 and persist it")
    parser.add_argument("--remove", action="append", default=[], metavar="MAC",
                        help="Explicitly remove a device reservation")
    parser.add_argument("--record", type=Path, help="Create a new raw serial JSONL recording (existing files refused)")
    parser.add_argument("--allow-w2", action="store_true", help="Accept legacy W2 for reference diagnostics only")
    parser.add_argument("--seconds", type=float, default=0, help="Stop serial capture after this duration; 0 until Ctrl+C")
    parser.add_argument("--speed", type=float, default=0, help="Replay timing multiplier; 0 = as fast as possible")
    parser.add_argument("--timeout-ms", type=int, default=250)
    parser.add_argument("--pid", type=int, help="Exact already-running Dolphin PID")
    parser.add_argument("--dolphin-exe", type=Path, help="Exact executable path of the selected Dolphin PID")
    parser.add_argument("--descriptor", type=lambda value: int(value, 0), help="Guest descriptor address from this build/debugger")
    parser.add_argument("--mem1-base", type=lambda value: int(value, 0), help="Explicit host virtual address of MEM1 for this Dolphin process")
    parser.add_argument("--mem2-base", type=lambda value: int(value, 0), help="Explicit host virtual address of MEM2 if used by descriptor")
    parser.add_argument("--manifest", type=Path, help="Generated wheel-bridge build manifest")
    parser.add_argument("--drive", action="store_true", help="Require guest wheel-input capability; rejected for diagnostic-only builds")
    return parser


def _registry(args: argparse.Namespace) -> DeviceRegistry:
    registry = DeviceRegistry.load(args.config)
    for address in args.remove:
        registry.remove(address)
    for assignment in args.assign:
        try:
            address, player = assignment.rsplit("=", 1)
            registry.assign(address, int(player))
        except (ValueError, MappingError) as exc:
            raise MappingError(f"Invalid assignment {assignment!r}: {exc}") from exc
    if args.remove or args.assign:
        registry.save(args.config)
        print(f"Saved explicit device reservations to {args.config}")
    return registry


def _summary(service: BridgeService, parser: StreamParser, *, now_ms: int | None = None,
             legacy: LegacySnapshot | None = None) -> str:
    view = service.view(now_ms=now_ms)
    sources = [{"slot": source, "flags": state.snapshot.flags,
                "buttons": state.snapshot.buttons,
                "accel": [state.snapshot.accel_x, state.snapshot.accel_y, state.snapshot.accel_z],
                "sample_sequence": state.snapshot.sample_sequence,
                "reported_age_ms": state.snapshot.sample_age_ms}
               for source, state in enumerate(service.slots) if state.snapshot is not None]
    legacy_view = ({"connected_mask": legacy.connected_mask,
                    "slots": [{"slot": slot.slot_id, "connected": slot.connected,
                               "calibrated": slot.calibrated, "buttons": slot.buttons,
                               "accel": [slot.accel_x, slot.accel_y, slot.accel_z],
                               "sequence": slot.sequence, "trick": slot.trick}
                              for slot in legacy.slots]} if legacy is not None else None)
    return json.dumps({"boot_session": view.boot_session, "players_fresh": list(view.players),
                       "devices": service.devices, "sources": sources, "legacy_reference": legacy_view,
                       "faults": list(view.faults),
                       "pending_events": sum(len(state.pending) for state in service.slots),
                       "frames": parser.frames_decoded, "invalid_frames": parser.invalid_frames,
                       "discarded_bytes": parser.discarded_bytes, "service": service.counters}, sort_keys=True)


def _replay(args: argparse.Namespace, service: BridgeService, parser: StreamParser) -> None:
    started = time.monotonic()
    end_ms = 0
    legacy = None
    for chunk in read_recording(args.replay):
        if args.speed:
            due = started + chunk.elapsed_ns / 1_000_000_000 / args.speed
            while time.monotonic() < due:
                time.sleep(max(0, min(0.05, due - time.monotonic())))
        end_ms = chunk.elapsed_ns // 1_000_000
        for frame in parser.feed(chunk.data):
            if isinstance(frame, Frame):
                service.ingest(frame, now_ms=end_ms)
            else:
                legacy = frame
        service.drain_diagnostic_events()
    print(_summary(service, parser, now_ms=end_ms, legacy=legacy))
    print("Replay completed offline; no serial port or Dolphin process was accessed.")


def _serial(args: argparse.Namespace, service: BridgeService, parser: StreamParser) -> None:
    port = choose_port(available_ports(), args.port)
    try:
        import serial
    except ImportError as exc:
        raise PortSelectionError("Install pyserial into this project's Python environment") from exc
    memory = None
    mailbox = None
    try:
        if args.attach:
            from .windows_memory import WindowsProcessMemory
            manifest = BuildManifest.load(args.manifest)
            memory = WindowsProcessMemory(args.pid, args.dolphin_exe,
                                          mem1_base=args.mem1_base, mem2_base=args.mem2_base)
            mailbox = GuestMailbox(memory, args.descriptor, manifest)
            if not mailbox.descriptor.capabilities & 1:
                raise MailboxError("Selected guest does not expose diagnostic bridge transport")
            if args.drive and not mailbox.descriptor.capabilities & 2:
                raise MailboxError("This build is diagnostic-only: wheel gameplay binding is not implemented")
            if mailbox.descriptor.capabilities & 2 and not args.drive:
                raise MailboxError("A wheel-input build requires explicit --drive; --attach alone is diagnostic-only")
            print("Guest mailbox verified. " + ("Wheel-input capability present." if args.drive else
                                                "Diagnostic attachment; this does not prove wheel gameplay."))
        with contextlib.ExitStack() as stack:
            recorder = stack.enter_context(RecordingWriter(args.record)) if args.record else None
            connection = stack.enter_context(serial.Serial(port.device, args.baud, timeout=0.01, write_timeout=0.1))
            print(f"Opened {port.device} at {args.baud}; {'guest attachment' if mailbox else 'diagnostic sink only'}")
            started_ms = time.monotonic_ns() // 1_000_000
            deadline_ms = started_ms + int(args.seconds * 1000) if args.seconds else None
            next_summary = started_ms
            next_publish = started_ms
            next_ack = started_ms
            ack_sequence = 0
            legacy = None
            while True:
                now_ms = time.monotonic_ns() // 1_000_000
                if deadline_ms is not None and now_ms >= deadline_ms:
                    break
                data = connection.read(min(max(connection.in_waiting, 1), 4096))
                now_ms = time.monotonic_ns() // 1_000_000
                if data:
                    if recorder:
                        recorder.append(data)
                    for frame in parser.feed(data):
                        if isinstance(frame, Frame):
                            service.ingest(frame, now_ms=now_ms)
                        else:
                            legacy = frame
                if mailbox and service.boot_session is not None and now_ms >= next_publish:
                    mailbox.publish(service.view(now_ms=now_ms), host_elapsed_ms=now_ms - started_ms)
                    try:
                        status = mailbox.read_status()
                    except MailboxBusyError:
                        status = None
                    if (status is not None and status.host_session == mailbox.host_session
                            and status.source_session == service.boot_session and status.flags & 2):
                        service.acknowledge_guest(status.acknowledged_events)
                    next_publish = now_ms + 16
                if not mailbox:
                    service.drain_diagnostic_events()
                if service.boot_session is not None and now_ms >= next_ack:
                    ack_sequence = (ack_sequence + 1) & 0xFFFFFFFF
                    acknowledgement = encode_frame(Frame(MessageKind.ACK, service.boot_session,
                                                          ack_sequence, (now_ms - started_ms) & 0xFFFFFFFF,
                                                          service.ack_records()))
                    if connection.write(acknowledgement) != len(acknowledgement):
                        raise PortSelectionError("Serial ACK write incomplete")
                    next_ack = now_ms + 33
                if now_ms >= next_summary:
                    print(_summary(service, parser, now_ms=now_ms, legacy=legacy))
                    next_summary = now_ms + 1000
    finally:
        if memory is not None:
            memory.close()


def main(argv: list[str] | None = None) -> int:
    parser = argument_parser()
    args = parser.parse_args(argv)
    if args.seconds < 0 or args.speed < 0 or args.baud <= 0:
        parser.error("Durations/speed cannot be negative and baud must be positive")
    if args.attach:
        missing = [name for name in ("pid", "dolphin_exe", "descriptor", "mem1_base", "manifest")
                   if getattr(args, name) is None]
        if missing:
            parser.error("--attach requires " + ", ".join("--" + name.replace("_", "-") for name in missing))
        if args.allow_w2:
            parser.error("Legacy W2 is reference-only and cannot attach to the new guest ABI")
    elif args.drive:
        parser.error("--drive requires explicit --attach and a guest with wheel-input capability")
    if args.record and not (args.diagnose or args.attach):
        parser.error("--record requires --diagnose or --attach; replay input is never overwritten")
    try:
        registry = _registry(args)
        if args.ports:
            for port in available_ports():
                print(f"{port.device}: {port.description} candidate={port.candidate} vid={port.vid!r} pid={port.pid!r}")
            return 0
        if not (args.diagnose or args.replay or args.attach):
            if args.assign or args.remove:
                return 0
            parser.print_help()
            return 0
        service = BridgeService(registry, timeout_ms=args.timeout_ms)
        stream = StreamParser(allow_w2=args.allow_w2)
        if args.replay:
            _replay(args, service, stream)
        else:
            _serial(args, service, stream)
        return 0
    except KeyboardInterrupt:
        print("Stopped. Guest timeout will neutralize a previously attached input stream.")
        return 0
    except (MappingError, PortSelectionError, RecordingError, MailboxError, OSError, ValueError) as exc:
        print(f"Bridge error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
