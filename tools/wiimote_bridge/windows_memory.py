"""Explicit-PID Windows backend with explicitly supplied Dolphin RAM bases.

RAM discovery is intentionally not guessed. Obtain these bases from the selected
Dolphin process/debugger. Game ID + descriptor ABI/build/CRC are then verified by
GuestMailbox before the sole permitted input-buffer write range is authorized.
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path

from .mailbox import MailboxError, valid_range


class WindowsProcessMemory:
    def __init__(self, pid: int, executable: Path, *, mem1_base: int,
                 mem2_base: int | None = None) -> None:
        if os.name != "nt" or ctypes.sizeof(ctypes.c_void_p) != 8:
            raise MailboxError("Live process access requires 64-bit Windows Python")
        if pid <= 0 or mem1_base <= 0 or (mem2_base is not None and mem2_base <= 0):
            raise MailboxError("A PID and explicit positive host RAM bases are required")
        expected = executable.resolve(strict=True)
        if expected.name.lower() not in ("dolphin.exe", "dolphinqt2.exe", "dolphinwx.exe"):
            raise MailboxError("The selected executable is not a supported Dolphin executable")
        self.pid = pid
        self.expected_executable = os.path.normcase(str(expected))
        self.mem1_base = mem1_base
        self.mem2_base = mem2_base
        self.write_range: tuple[int, int] | None = None
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        handle_type = ctypes.c_void_p
        self.kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        self.kernel.OpenProcess.restype = handle_type
        self.kernel.CloseHandle.argtypes = [handle_type]
        self.kernel.CloseHandle.restype = ctypes.c_int
        self.kernel.QueryFullProcessImageNameW.argtypes = [handle_type, ctypes.c_uint32,
                                                          ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_uint32)]
        self.kernel.QueryFullProcessImageNameW.restype = ctypes.c_int
        self.kernel.GetProcessTimes.argtypes = [handle_type] + [ctypes.c_void_p] * 4
        self.kernel.GetProcessTimes.restype = ctypes.c_int
        self.kernel.WaitForSingleObject.argtypes = [handle_type, ctypes.c_uint32]
        self.kernel.WaitForSingleObject.restype = ctypes.c_uint32
        self.kernel.ReadProcessMemory.argtypes = [handle_type, ctypes.c_void_p, ctypes.c_void_p,
                                                  ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
        self.kernel.ReadProcessMemory.restype = ctypes.c_int
        self.kernel.WriteProcessMemory.argtypes = self.kernel.ReadProcessMemory.argtypes
        self.kernel.WriteProcessMemory.restype = ctypes.c_int
        # Query + synchronization + precisely the operations needed by this
        # explicit target handle. No process-name hook and no debug privilege.
        rights = 0x1000 | 0x00100000 | 0x0010 | 0x0020 | 0x0008
        self.handle = self.kernel.OpenProcess(rights, False, pid)
        if not self.handle:
            raise MailboxError(f"Cannot open selected Dolphin PID {pid}: Win32 {ctypes.get_last_error()}")
        try:
            self.creation_time = self._creation_time()
            self.ensure_target()
        except BaseException:
            self.close()
            raise

    def _creation_time(self) -> int:
        times = [ctypes.c_uint64() for _ in range(4)]
        if not self.kernel.GetProcessTimes(self.handle, *(ctypes.byref(value) for value in times)):
            raise MailboxError("Cannot verify selected Dolphin process creation time")
        return times[0].value

    def ensure_target(self) -> None:
        if not self.handle or self.kernel.WaitForSingleObject(self.handle, 0) != 0x102:
            raise MailboxError("Selected Dolphin process has exited")
        size = ctypes.c_uint32(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not self.kernel.QueryFullProcessImageNameW(self.handle, 0, buffer, ctypes.byref(size)):
            raise MailboxError("Cannot verify selected Dolphin executable")
        if os.path.normcase(str(Path(buffer.value).resolve())) != self.expected_executable:
            raise MailboxError("Selected PID does not match the explicitly selected Dolphin executable")
        if self._creation_time() != self.creation_time:
            raise MailboxError("Dolphin process identity changed")

    def _host_address(self, address: int, size: int) -> int:
        if not valid_range(address & ~3, size + (address & 3)):
            raise MailboxError("Access is outside supported guest RAM")
        if 0x80000000 <= address and address + size <= 0x81800000:
            return self.mem1_base + address - 0x80000000
        if self.mem2_base is not None and 0x90000000 <= address and address + size <= 0x94000000:
            return self.mem2_base + address - 0x90000000
        raise MailboxError("This guest RAM mapping was not explicitly supplied")

    def authorize_write_range(self, address: int, size: int) -> None:
        if not valid_range(address, size):
            raise MailboxError("Cannot authorize an invalid guest write range")
        self._host_address(address, size)
        self.write_range = (address, address + size)

    def read(self, address: int, size: int) -> bytes:
        self.ensure_target()
        if size <= 0 or size > 4096:
            raise MailboxError("Live reads are bounded to 1..4096 bytes")
        buffer = ctypes.create_string_buffer(size)
        transferred = ctypes.c_size_t()
        host = self._host_address(address, size)
        if not self.kernel.ReadProcessMemory(self.handle, host, buffer, size, ctypes.byref(transferred)):
            raise MailboxError(f"Dolphin read failed: Win32 {ctypes.get_last_error()}")
        if transferred.value != size:
            raise MailboxError("Dolphin read was incomplete")
        return buffer.raw

    def write(self, address: int, data: bytes) -> None:
        self.ensure_target()
        if not self.write_range or not (self.write_range[0] <= address
                                        and address + len(data) <= self.write_range[1]):
            raise MailboxError("Write is outside the validated bridge input buffer")
        host = self._host_address(address, len(data))
        buffer = ctypes.create_string_buffer(data)
        transferred = ctypes.c_size_t()
        if not self.kernel.WriteProcessMemory(self.handle, host, buffer, len(data), ctypes.byref(transferred)):
            raise MailboxError(f"Dolphin write failed: Win32 {ctypes.get_last_error()}")
        if transferred.value != len(data):
            raise MailboxError("Dolphin write was incomplete; guest commit stays incomplete")

    def close(self) -> None:
        if getattr(self, "handle", None):
            self.kernel.CloseHandle(self.handle)
            self.handle = None
