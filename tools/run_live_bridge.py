#!/usr/bin/env python3
"""Run Mario Kart Wii 8-Player Splitscreen with live ESP32 Wheel Bridge.

Launches Dolphin (or connects to a running Dolphin instance), detects the
Pulsar GuestMailbox in MEM1, attaches the ESP32 on COM3, and bridges physical
Wiimotes into Players 5-8 live in real-time until Ctrl+C.
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
    ap.add_argument("--port", default="COM3", help="Serial port of the ESP32 (default: COM3)")
    ap.add_argument("--baud", type=int, default=115200, help="ESP32 UART baud rate (default: 115200)")
    ap.add_argument("--timeout", type=float, default=60.0, help="Timeout waiting for Dolphin descriptor")
    args = ap.parse_args()

    layout = Layout(args.root, vanilla=True)

    manifest_paths = [
        ROOT / "build/code-vanilla-menu-wheel/wheel-bridge-manifest.json",
        ROOT / "build/code-vanilla-wheel/wheel-bridge-manifest.json",
    ]
    manifest_path = next((p for p in manifest_paths if p.exists()), None)
    if not manifest_path:
        print("Error: No wheel-bridge manifest found!", file=sys.stderr)
        return 1

    manifest = BuildManifest.load(manifest_path)
    print(f"[bridge] Loaded build manifest {manifest.build_id.hex()} (game_id={manifest.game_id})")

    # Clear stale log
    if layout.dolphin_log.exists():
        try:
            layout.dolphin_log.unlink()
        except OSError:
            pass

    # Launch Dolphin if not running
    exe = Path(r"C:\Users\Till\Desktop\Dolphin-x64\Dolphin.exe")
    cmd = [
        str(exe),
        "-u", str(layout.dolphin),
        "-C", "GFX.Settings.InternalResolution=1",
        "-C", "GFX.Enhancements.MaxAnisotropy=0",
        "-e", str(layout.launch),
    ]
    print(f"[bridge] Starting Dolphin: {' '.join(cmd)}")
    proc = subprocess.Popen(cmd)
    pid = proc.pid
    created = process_created(pid)
    layout.pid_file.write_text(f"{pid} {created}\n", encoding="utf-8")
    print(f"[bridge] Dolphin running with PID {pid}")

    try:
        print(f"[bridge] Waiting up to {args.timeout}s for guest descriptor in {layout.dolphin_log.name}...")
        descriptor_addr = None
        session = None
        log_pos = 0
        desc_pattern = re.compile(r"ss8 wheel bridge:.*?descriptor=([0-9a-fA-F]+)\s+session=([0-9a-fA-F]+)\s+abi=(\d+)\s+cap=(\d+)")

        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            if not dolphin_alive(pid, created):
                print("[bridge] Error: Dolphin closed unexpectedly!", file=sys.stderr)
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
                                print(f"[bridge] Found guest mailbox descriptor: {descriptor_addr:#010x} (session {session:#010x})")
                                break
                except OSError:
                    pass

            if descriptor_addr is not None:
                break
            time.sleep(0.5)

        if descriptor_addr is None:
            print("[bridge] Error: Timed out waiting for guest descriptor in dolphin.log", file=sys.stderr)
            return 3

        # Discover MEM1 base
        backend = WindowsProcessMemory(pid, exe, mem1_base=1)
        mem1_base = find_mem1(backend.handle, backend.kernel)
        backend.close()

        if mem1_base is None:
            print("[bridge] Error: MEM1 base address could not be located in Dolphin!", file=sys.stderr)
            return 4

        print(f"[bridge] Located MEM1 base at: {mem1_base:#018x}")

        # Verify Mailbox
        backend = WindowsProcessMemory(pid, exe, mem1_base=mem1_base)
        mailbox = GuestMailbox(backend, descriptor_addr, manifest)
        print(f"[bridge] Verified guest mailbox capabilities: {mailbox.descriptor.capabilities}")
        backend.close()

        # Run bridge process
        bridge_cmd = [
            sys.executable, "-m", "tools.wiimote_bridge",
            "--attach", "--drive",
            "--port", args.port,
            "--baud", str(args.baud),
            "--pid", str(pid),
            "--dolphin-exe", str(exe),
            "--descriptor", hex(descriptor_addr),
            "--mem1-base", hex(mem1_base),
            "--manifest", str(manifest_path),
            "--seconds", "0",
        ]
        print(f"\n=======================================================")
        print(f"  ESP32 LIVE WHEEL BRIDGE ACTIVE (PORT {args.port})")
        print(f"=======================================================")
        print(f"  Players 1-4: Emulated/Local controls (GameCube 1-4)")
        print(f"  Players 5-8: Physical Wiimotes connected to ESP32")
        print(f"  Press Ctrl+C to stop the bridge and close Dolphin.")
        print(f"=======================================================\n")

        bridge_proc = subprocess.run(bridge_cmd)
        return bridge_proc.returncode

    except KeyboardInterrupt:
        print("\n[bridge] Stopping live bridge...")
        return 0

    finally:
        stop_cmd = [sys.executable, str(ROOT / "tools/install_8p.py"), "--vanilla", "--root", str(layout.root), "stop"]
        subprocess.run(stop_cmd, check=False)
        print("[bridge] Dolphin stopped. Clean exit.")


if __name__ == "__main__":
    raise SystemExit(main())
