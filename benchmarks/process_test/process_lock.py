
"""Windows named mutex for synchronizing separate Python processes."""

import ctypes
from ctypes import wintypes


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

kernel32.CreateMutexW.argtypes = [
    wintypes.LPVOID,
    wintypes.BOOL,
    wintypes.LPCWSTR,
]
kernel32.CreateMutexW.restype = wintypes.HANDLE

kernel32.WaitForSingleObject.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
]
kernel32.WaitForSingleObject.restype = wintypes.DWORD

kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
kernel32.ReleaseMutex.restype = wintypes.BOOL

kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL


WAIT_OBJECT_0 = 0x00000000
WAIT_ABANDONED = 0x00000080
INFINITE = 0xFFFFFFFF


class NamedMutex:
    """A named Windows mutex shared by processes."""

    def __init__(self, name="ChronosMatchRingBufferLock"):
        self.name = name
        self.handle = kernel32.CreateMutexW(
            None,
            False,
            self.name,
        )

        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())

    def __enter__(self):
        result = kernel32.WaitForSingleObject(
            self.handle,
            INFINITE,
        )

        if result not in (WAIT_OBJECT_0, WAIT_ABANDONED):
            raise ctypes.WinError(ctypes.get_last_error())

        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if not kernel32.ReleaseMutex(self.handle):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle:
            kernel32.CloseHandle(self.handle)
            self.handle = None
