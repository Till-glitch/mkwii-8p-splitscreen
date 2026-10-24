"""Serial port selection; an arbitrary USB device is never selected implicitly."""
from __future__ import annotations

from dataclasses import dataclass


class PortSelectionError(RuntimeError):
    pass


# Common USB/UART chips used by ESP32 dev boards. These identify a candidate,
# never a trusted W3 peer; valid packets and device identities remain required.
KNOWN_UART_IDS = {(0x10C4, 0xEA60), (0x1A86, 0x7523), (0x1A86, 0x55D4),
                  (0x0403, 0x6001), (0x0403, 0x6015)}


@dataclass(frozen=True)
class PortInfo:
    device: str
    description: str = ""
    vid: int | None = None
    pid: int | None = None
    serial_number: str | None = None

    @property
    def candidate(self) -> bool:
        return (self.vid, self.pid) in KNOWN_UART_IDS


def available_ports() -> list[PortInfo]:
    try:
        from serial.tools import list_ports
    except ImportError as exc:
        raise PortSelectionError("Serial access needs pyserial in this project's Python environment") from exc
    return [PortInfo(p.device, p.description or "", p.vid, p.pid, p.serial_number)
            for p in list_ports.comports()]


def choose_port(ports: list[PortInfo], explicit: str | None = None) -> PortInfo:
    if explicit:
        matches = [p for p in ports if p.device.casefold() == explicit.casefold()]
        if len(matches) == 1:
            return matches[0]
        raise PortSelectionError(f"Selected serial port {explicit!r} is not present")
    candidates = [p for p in ports if p.candidate]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise PortSelectionError("No known ESP32 USB/UART candidate found; use --ports and --port explicitly")
    names = ", ".join(p.device for p in candidates)
    raise PortSelectionError(f"Multiple USB/UART candidates ({names}); select one with --port")
