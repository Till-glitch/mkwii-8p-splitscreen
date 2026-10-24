"""Explicit, persistent Wiimote identity reservations (no serial-order mapping)."""
from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


class MappingError(ValueError):
    pass


def normalize_mac(value: bytes | str) -> str:
    if isinstance(value, bytes):
        if len(value) != 6:
            raise MappingError("A Bluetooth address must contain six bytes")
        compact = value.hex()
    elif isinstance(value, str):
        compact = value.replace(":", "").replace("-", "").upper()
        if not re.fullmatch(r"[0-9A-F]{12}", compact):
            raise MappingError(f"Invalid Bluetooth address: {value!r}")
    else:
        raise MappingError("A Bluetooth address must be bytes or text")
    if compact.upper() in ("000000000000", "FFFFFFFFFFFF"):
        raise MappingError("An empty/broadcast address cannot reserve a player")
    return ":".join(compact[i:i + 2] for i in range(0, 12, 2)).upper()


@dataclass
class DeviceRegistry:
    assignments: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized: dict[str, int] = {}
        for address, player in self.assignments.items():
            if type(player) is not int or player not in range(5, 9):
                raise MappingError("Bridge players must be integers from 5 to 8")
            key = normalize_mac(address)
            if key in normalized or player in normalized.values():
                raise MappingError("Each device and each player may be reserved only once")
            normalized[key] = player
        self.assignments = normalized

    def player_for(self, address: bytes | str) -> int | None:
        return self.assignments.get(normalize_mac(address))

    def assign(self, address: bytes | str, player: int) -> None:
        if type(player) is not int or player not in range(5, 9):
            raise MappingError("Bridge players must be integers from 5 to 8")
        key = normalize_mac(address)
        existing = self.assignments.get(key)
        if existing is not None and existing != player:
            raise MappingError(f"{key} is already reserved for P{existing}; remove it explicitly first")
        for other, reserved in self.assignments.items():
            if reserved == player and other != key:
                raise MappingError(f"P{player} is already reserved for {other}; remove it explicitly first")
        self.assignments[key] = player

    def remove(self, address: bytes | str) -> None:
        self.assignments.pop(normalize_mac(address), None)

    @classmethod
    def load(cls, path: Path) -> DeviceRegistry:
        try:
            with path.open(encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError) as exc:
            raise MappingError(f"Cannot read mapping {path}: {exc}") from exc
        if not isinstance(data, dict) or data.get("version") != 1:
            raise MappingError("Mapping must be an object with version 1")
        assignments = data.get("assignments")
        if not isinstance(assignments, dict):
            raise MappingError("Mapping assignments must be an object")
        return cls(assignments)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"version": 1, "assignments": dict(sorted(self.assignments.items()))}
        temp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                             prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
                temp_name = handle.name
                json.dump(data, handle, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            if temp_name and os.path.exists(temp_name):
                os.unlink(temp_name)
