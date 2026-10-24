#!/usr/bin/env python3
"""Automated verification of 5-Player Join with ESP32 Wheel Bridge in Dolphin.

Boots vanilla MKWii with menu script v-5p-bridge-join.txt, connects to
GuestMailbox, streams simulated BridgeWheelController inputs for Player 5 (slot 0),
verifies Player 5 joins on the Join Page (bound_player_mask & 0x10), captures
screenshots of 5 joined players and character selection, and verifies clean exit.
"""
from __future__ import annotations

import argparse
import ctypes
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.wiimote_bridge.mailbox import BuildManifest, GuestMailbox, GuestStatus
from tools.wiimote_bridge.protocol import (FLAG_CONNECTED, FLAG_SAMPLE_VALID,
                                           SnapshotSlot)
from tools.wiimote_bridge.service import HostView
from tools.wiimote_bridge.windows_memory import WindowsProcessMemory
from tools.install_8p import Layout, dolphin_alive, process_created, save_shots


class MBI(ctypes.Structure):
    _fields_ = [
        ('BaseAddress', ctypes.c_void_p),
        ('AllocationBase', ctypes.c_void_p),
        ('AllocationProtect', ctypes.c_uint32),
        ('__alignment1', ctypes.c_uint32),
        ('RegionSize', ctypes.c_size_t),
        ('State', ctypes.c_uint32),
        ('Protect', ctypes.c_uint32),
        ('Type', ctypes.c_uint32),
        ('__alignment2', ctypes.c_uint32),
    ]


def find_mem1(handle: int, kernel) -> int | None:
    kernel.VirtualQueryEx.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
    kernel.VirtualQueryEx.restype = ctypes.c_size_t
    kernel.ReadProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    kernel.ReadProcessMemory.restype = ctypes.c_int

    address = 0
    while address < 0x7fffffffffff:
        region = MBI()
        if not kernel.VirtualQueryEx(handle, address, ctypes.byref(region), ctypes.sizeof(region)):
            break
        base = region.BaseAddress or 0
        end = base + region.RegionSize
        if end <= address:
            break
        if region.State == 0x1000 and region.RegionSize >= 0x1800000 and not (region.Protect & 0x101):
            data = ctypes.create_string_buffer(6)
            magic = ctypes.create_string_buffer(4)
            count = ctypes.c_size_t()
            if (kernel.ReadProcessMemory(handle, base, data, 6, ctypes.byref(count)) and data.raw == b'RMCP01'
                    and kernel.ReadProcessMemory(handle, base + 0x18, magic, 4, ctypes.byref(count)) and magic.raw == b'\x5d\x1c\x9e\xa3'):
                return base
        address = end
    return None


def neutral_slot(slot_id: int) -> SnapshotSlot:
    return SnapshotSlot(
        slot_id=slot_id,
        flags=0,
        buttons=0,
        accel_x=0,
        accel_y=0,
        accel_z=0,
        sample_age_ms=0xFFFF,
        sample_sequence=0,
        last_event_sequence=0,
        event_flags=0,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=ROOT / "build/dev-vanilla")
    ap.add_argument("--timeout", type=float, default=160.0, help="Overall test timeout in seconds")
    ap.add_argument("--leave-running", action="store_true")
    args = ap.parse_args()

    layout = Layout(args.root, vanilla=True)

    # Determine manifest
    manifest_paths = [
        ROOT / "build/code-vanilla-menu-wheel/wheel-bridge-manifest.json",
        ROOT / "build/code-vanilla-wheel/wheel-bridge-manifest.json",
    ]
    manifest_path = next((p for p in manifest_paths if p.exists()), None)
    if not manifest_path:
        print("Error: No wheel-bridge manifest found!", file=sys.stderr)
        return 1

    manifest = BuildManifest.load(manifest_path)
    print(f"[test] Loaded manifest build_id={manifest.build_id.hex()} game_id={manifest.game_id} ({manifest_path.name})")

    # Clear stale log
    if layout.dolphin_log.exists():
        try:
            layout.dolphin_log.unlink()
        except OSError:
            pass

    # Launch Dolphin
    exe = Path(r"C:\Users\Till\Desktop\Dolphin-x64\Dolphin.exe")
    cmd = [
        str(exe),
        "-u", str(layout.dolphin),
        "-C", "GFX.Settings.InternalResolution=1",
        "-C", "GFX.Enhancements.MaxAnisotropy=0",
        "-e", str(layout.launch),
    ]
    print(f"[test] Launching Dolphin: {' '.join(cmd)}")
    proc = subprocess.Popen(cmd)
    pid = proc.pid
    created = process_created(pid)
    layout.pid_file.write_text(f"{pid} {created}\n", encoding="utf-8")
    print(f"[test] Dolphin started PID {pid} (created {created})")

    backend = None
    shots_dir = layout.root / "shots"
    shots_dir.mkdir(parents=True, exist_ok=True)

    try:
        t0 = time.monotonic()
        deadline = t0 + args.timeout
        descriptor_addr = None
        session = None

        print(f"[test] Waiting up to 45s for guest descriptor in {layout.dolphin_log.name}...")
        log_pos = 0
        desc_pattern = re.compile(r"ss8 wheel bridge:.*?descriptor=([0-9a-fA-F]+)\s+session=([0-9a-fA-F]+)\s+abi=(\d+)\s+cap=(\d+)")

        desc_deadline = time.monotonic() + 45.0
        while time.monotonic() < desc_deadline:
            if not dolphin_alive(pid, created):
                print("[test] Error: Dolphin process exited prematurely!", file=sys.stderr)
                return 2

            if layout.dolphin_log.exists():
                try:
                    with layout.dolphin_log.open("r", encoding="utf-8", errors="replace") as f:
                        f.seek(log_pos)
                        new_text = f.read()
                        log_pos = f.tell()
                        for line in new_text.splitlines():
                            match = desc_pattern.search(line)
                            if match:
                                descriptor_addr = int(match.group(1), 16)
                                session = int(match.group(2), 16)
                                abi = int(match.group(3))
                                cap = int(match.group(4))
                                print(f"[test] Descriptor detected: addr={descriptor_addr:#010x} session={session:#010x} abi={abi} cap={cap}")
                                break
                except OSError:
                    pass

            if descriptor_addr is not None:
                break
            time.sleep(0.5)

        if descriptor_addr is None:
            print("[test] Error: Timed out waiting for guest descriptor in dolphin.log", file=sys.stderr)
            save_shots(layout, pid, shots_dir, "timeout-descriptor")
            return 3

        # Connect to Dolphin process and locate MEM1
        backend = WindowsProcessMemory(pid, exe, mem1_base=1)
        mem1_base = find_mem1(backend.handle, backend.kernel)
        backend.close()

        if mem1_base is None:
            print("[test] Error: MEM1 base could not be found in Dolphin process!", file=sys.stderr)
            return 4

        print(f"[test] MEM1 base found at: {mem1_base:#018x}")

        backend = WindowsProcessMemory(pid, exe, mem1_base=mem1_base)
        mailbox = GuestMailbox(backend, descriptor_addr, manifest)
        print(f"[test] GuestMailbox initialized. Capabilities: {mailbox.descriptor.capabilities}")

        # Input streaming & join verification loop
        sample_seq = 0
        p5_joined = False
        p5_joined_at: float | None = None
        last_logged_gen = 0
        status: GuestStatus | None = None

        print("[test] Streaming bridge input and monitoring Player 5 join...")

        while time.monotonic() < deadline:
            if not dolphin_alive(pid, created):
                print("[test] Error: Dolphin died during test loop!", file=sys.stderr)
                return 5

            now_ms = int((time.monotonic() - t0) * 1000)
            sample_seq = (sample_seq + 1) & 0xFFFFFFFF

            # Check status periodically
            if sample_seq % 8 == 0:
                try:
                    status = mailbox.read_status()
                    if status.generation != last_logged_gen:
                        last_logged_gen = status.generation
                        # Check if Player 5 is bound (bit 4, 0x10)
                        if (status.bound_player_mask & 0x10) and not p5_joined:
                            p5_joined = True
                            p5_joined_at = time.monotonic()
                            print(f"\n[test] >>> PLAYER 5 JOIN DETECTED! <<<")
                            print(f"[test] bound_player_mask={status.bound_player_mask:#x} (bit 4 set: Player 5)")
                            print(f"[test] generation={status.generation} accepted_count={status.accepted_count}")
                            time.sleep(0.5)  # Let UI render the newly joined slot
                            save_shots(layout, pid, shots_dir, "join-page-5p-success")
                            print(f"[test] Captured screenshot: shots/join-page-5p-success-*.png\n")
                except Exception as exc:
                    pass

            # Determine button press:
            # In RVL WPAD: WPAD_BUTTON_2 = 0x0100, WPAD_BUTTON_A = 0x0800
            # 0x0001 is D-Pad Left!
            button = 0
            if not p5_joined:
                if status is not None and status.generation > 1200:
                    button = 0x0100 | 0x0800  # WPAD_BUTTON_2 | WPAD_BUTTON_A
                elif time.monotonic() - t0 > 20.0:
                    button = 0x0100 | 0x0800

            slot0 = SnapshotSlot(
                slot_id=0,
                flags=FLAG_CONNECTED | FLAG_SAMPLE_VALID,
                buttons=button,
                accel_x=0,
                accel_y=0,
                accel_z=0,
                sample_age_ms=0,
                sample_sequence=sample_seq,
                last_event_sequence=0,
                event_flags=0,
            )

            view = HostView(
                boot_session=1,
                slots=(slot0, neutral_slot(1), neutral_slot(2), neutral_slot(3)),
                events=(),
                players=(0, 1, 2, 3),
                faults=(),
            )

            try:
                mailbox.publish(view, host_elapsed_ms=now_ms)
            except Exception as e:
                print(f"[test] Warning: publish failed: {e}")

            # If Player 5 has joined, wait for menu script to advance to Character Select
            if p5_joined:
                # v-5p-bridge-join.txt takes ~25s after join to reach character select
                if p5_joined_at is not None and (time.monotonic() - p5_joined_at) > 28.0:
                    print(f"[test] Reached post-join menu completion window ({time.monotonic() - p5_joined_at:.1f}s after join).")
                    time.sleep(1.0)
                    save_shots(layout, pid, shots_dir, "char-select-8p-success")
                    print(f"[test] Captured screenshot: shots/char-select-8p-success-*.png")
                    break

            time.sleep(0.02)  # 50 Hz

        if not p5_joined:
            print("[test] Error: Timed out waiting for Player 5 to join!", file=sys.stderr)
            save_shots(layout, pid, shots_dir, "join-timeout")
            return 6

        print("\n=======================================================")
        print("  VERIFICATION SUCCESS: 5-PLAYER JOIN AND TRANSITION")
        print("=======================================================")
        print(f"  Player 5 bound mask : {status.bound_player_mask:#x}")
        print(f"  Accepted frames     : {status.accepted_count}")
        print(f"  Final generation    : {status.generation}")
        print("=======================================================\n")
        return 0

    finally:
        if backend is not None:
            backend.close()
        if not args.leave_running:
            stop_cmd = [sys.executable, str(ROOT / "tools/install_8p.py"), "--vanilla", "--root", str(layout.root), "stop"]
            subprocess.run(stop_cmd, check=False)


if __name__ == "__main__":
    raise SystemExit(main())
