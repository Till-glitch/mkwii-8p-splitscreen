#!/usr/bin/env python3
"""Automated live verification of Dolphin + SplitScreen8 Wheel Bridge.

Boots vanilla MKWii in Dolphin, waits for the guest descriptor log,
discovers Dolphin's MEM1 base, verifies the guest mailbox, and captures screenshots.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.wiimote_bridge.mailbox import BuildManifest, GuestMailbox
from tools.wiimote_bridge.windows_memory import WindowsProcessMemory
from tools.install_8p import Layout, process_created, dolphin_alive


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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=ROOT / "build/dev-vanilla")
    ap.add_argument("--timeout", type=float, default=45.0)
    ap.add_argument("--leave-running", action="store_true")
    ap.add_argument("--bridge", action="store_true", help="Stream live inputs via wiimote_bridge")
    ap.add_argument("--port", default="COM3", help="Serial port for ESP32")
    ap.add_argument("--bridge-seconds", type=float, default=10.0, help="Bridge run duration in seconds")
    args = ap.parse_args()

    layout = Layout(args.root, vanilla=True)
    manifest_path = ROOT / "build/code-vanilla-wheel/wheel-bridge-manifest.json"
    if not manifest_path.exists():
        print(f"Error: manifest missing at {manifest_path}", file=sys.stderr)
        return 1

    manifest = BuildManifest.load(manifest_path)
    print(f"[test] Loaded manifest build_id={manifest.build_id.hex()} game_id={manifest.game_id}")

    # Remove any stale dolphin.log
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
    print(f"[test] Launching: {' '.join(cmd)}")
    proc = subprocess.Popen(cmd)
    pid = proc.pid
    created = process_created(pid)
    layout.pid_file.write_text(f"{pid} {created}\n", encoding="utf-8")
    print(f"[test] Dolphin started PID {pid} (created {created})")

    try:
        deadline = time.monotonic() + args.timeout
        descriptor_addr = None
        session = None

        print(f"[test] Waiting up to {args.timeout}s for guest descriptor in {layout.dolphin_log.name}...")
        log_pos = 0
        desc_pattern = re.compile(r"ss8 wheel bridge:.*?descriptor=([0-9a-fA-F]+)\s+session=([0-9a-fA-F]+)\s+abi=(\d+)\s+cap=(\d+)")

        while time.monotonic() < deadline:
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
                                print(f"[test] Found descriptor: addr={descriptor_addr:#010x} session={session:#010x} abi={abi} cap={cap}")
                                break
                except OSError:
                    pass

            if descriptor_addr is not None:
                break
            time.sleep(0.5)

        if descriptor_addr is None:
            print("[test] Timed out waiting for guest descriptor in dolphin.log", file=sys.stderr)
            return 3

        # Connect to WindowsProcessMemory and find MEM1
        backend = WindowsProcessMemory(pid, exe, mem1_base=1)
        mem1_base = find_mem1(backend.handle, backend.kernel)
        backend.close()

        if mem1_base is None:
            print("[test] Error: could not find MEM1 base in Dolphin process memory!", file=sys.stderr)
            return 4

        print(f"[test] Found Dolphin MEM1 base: {mem1_base:#018x}")

        # Connect GuestMailbox
        backend = WindowsProcessMemory(pid, exe, mem1_base=mem1_base)
        mailbox = GuestMailbox(backend, descriptor_addr, manifest)

        print(f"[test] GuestMailbox connected! Descriptor verified:")
        print(f"       Capabilities: {mailbox.descriptor.capabilities} (CAP_DIAGNOSTIC=1, CAP_WHEEL_INPUT=2)")
        print(f"       Build ID: {mailbox.descriptor.build_id.hex()}")
        print(f"       Guest Session: {mailbox.descriptor.guest_session:#010x}")
        print(f"       Input Buffer: {mailbox.descriptor.input_address:#010x}")
        print(f"       Status Buffer: {mailbox.descriptor.status_address:#010x}")

        status = mailbox.read_status()
        print(f"[test] Read status from guest mailbox:")
        print(f"       Generation: {status.generation}")
        print(f"       Flags: {status.flags:#x} (ready={bool(status.flags & 1)}, applied={bool(status.flags & 2)})")
        print(f"       Last Error: {status.last_error}")
        print(f"       Accepted Count: {status.accepted_count}")
        print(f"       Rejected Count: {status.rejected_count}")
        print(f"       Bound Players Mask: {status.bound_player_mask:#x}")

        # Take a screenshot
        shot_dir = layout.root / "shots"
        shot_cmd = [sys.executable, str(ROOT / "tools/install_8p.py"), "--vanilla", "--root", str(layout.root), "shot", "--out", str(shot_dir)]
        subprocess.run(shot_cmd, check=False)
        print(f"[test] Captured screenshot to {shot_dir}")

        if args.bridge:
            backend.close()
            bridge_cmd = [
                sys.executable, "-m", "tools.wiimote_bridge",
                "--attach", "--drive",
                "--port", args.port,
                "--pid", str(pid),
                "--dolphin-exe", str(exe),
                "--descriptor", hex(descriptor_addr),
                "--mem1-base", hex(mem1_base),
                "--manifest", str(manifest_path),
                "--seconds", str(args.bridge_seconds),
            ]
            print(f"[test] Launching wiimote_bridge for {args.bridge_seconds}s...")
            res = subprocess.run(bridge_cmd, text=True, capture_output=True)
            print(f"[test] wiimote_bridge stdout:\n{res.stdout}")
            if res.stderr:
                print(f"[test] wiimote_bridge stderr:\n{res.stderr}", file=sys.stderr)
            if res.returncode != 0:
                print(f"[test] wiimote_bridge exited with code {res.returncode}", file=sys.stderr)
                return 5

        print("[test] SUCCESS! All verification checks passed.")
        return 0

    finally:
        if not args.leave_running:
            stop_cmd = [sys.executable, str(ROOT / "tools/install_8p.py"), "--vanilla", "--root", str(layout.root), "stop"]
            subprocess.run(stop_cmd, check=False)


if __name__ == "__main__":
    raise SystemExit(main())
