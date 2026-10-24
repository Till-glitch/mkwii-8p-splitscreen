"""Bounded JSONL serial recordings, usable without serial or Dolphin packages."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

MAX_CHUNK_BYTES = 4096
MAX_LINE_BYTES = 2 * MAX_CHUNK_BYTES + 1024


class RecordingError(ValueError):
    pass


@dataclass(frozen=True)
class RecordedChunk:
    elapsed_ns: int
    data: bytes


class RecordingWriter:
    def __init__(self, path: Path, *, started_ns: int | None = None) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = path.open("x", encoding="utf-8", newline="\n")
        self.started_ns = time.monotonic_ns() if started_ns is None else started_ns
        self.previous_ns = 0
        self.handle.write(json.dumps({"format": "ss8-wiimote-serial", "version": 1}) + "\n")
        self.handle.flush()

    def append(self, data: bytes, *, now_ns: int | None = None) -> None:
        if not data:
            return
        if len(data) > MAX_CHUNK_BYTES:
            raise RecordingError(f"A recording chunk cannot exceed {MAX_CHUNK_BYTES} bytes")
        elapsed = (time.monotonic_ns() if now_ns is None else now_ns) - self.started_ns
        if elapsed < self.previous_ns:
            raise RecordingError("Recording timestamps must be monotonic")
        self.previous_ns = elapsed
        self.handle.write(json.dumps({"elapsed_ns": elapsed, "data_hex": data.hex()}) + "\n")
        self.handle.flush()

    def close(self) -> None:
        self.handle.close()

    def __enter__(self) -> RecordingWriter:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def read_recording(path: Path) -> Iterator[RecordedChunk]:
    with path.open("rb") as handle:
        first = handle.readline(MAX_LINE_BYTES + 1)
        try:
            header = json.loads(first)
        except (UnicodeDecodeError, ValueError) as exc:
            raise RecordingError("Recording header is invalid") from exc
        if header != {"format": "ss8-wiimote-serial", "version": 1}:
            raise RecordingError("Unknown recording format/version")
        previous = 0
        for number in range(2, 2**63):
            line = handle.readline(MAX_LINE_BYTES + 1)
            if not line:
                break
            if len(line) > MAX_LINE_BYTES:
                raise RecordingError(f"Recording line {number} exceeds the limit")
            try:
                record = json.loads(line)
                elapsed = record["elapsed_ns"]
                encoded = record["data_hex"]
                if type(elapsed) is not int or elapsed < previous or not isinstance(encoded, str):
                    raise ValueError("invalid timestamp or bytes")
                data = bytes.fromhex(encoded)
                if not data or len(data) > MAX_CHUNK_BYTES:
                    raise ValueError("invalid chunk size")
            except (UnicodeDecodeError, ValueError, TypeError, KeyError) as exc:
                raise RecordingError(f"Invalid recording line {number}") from exc
            previous = elapsed
            yield RecordedChunk(elapsed, data)
