"""
ChronosMatch Zero-Copy High-Frequency Trading Engine
IPC Memory-Mapped Buffer module (Member 2)

Provides cross-platform shared memory mapping via mmap.
"""

import os
import mmap
from typing import Optional


class MmapBuffer:
    """
    Cross-platform shared memory buffer backed by mmap.
    Supports file-backed mmap (cross-process) and anonymous mmap (in-process).
    """

    def __init__(
        self,
        filepath: Optional[str] = None,
        size: int = 10 * 1024 * 1024,
        create: bool = True,
    ):
        """
        Initialize a memory-mapped buffer.

        Args:
            filepath: Path to backing file. If None, anonymous memory is allocated.
            size: Buffer size in bytes (defaults to 10 MB).
            create: Whether to create/truncate the backing file if it doesn't exist.
        """
        self.size = size
        self.filepath = filepath
        self.file_obj = None

        if filepath:
            os.makedirs(os.path.dirname(os.path.abspath(filepath)) or ".", exist_ok=True)
            if create:
                with open(filepath, "a+b") as f:
                    f.truncate(size)
            self.file_obj = open(filepath, "r+b")
            self.mm = mmap.mmap(self.file_obj.fileno(), size, access=mmap.ACCESS_WRITE)
        else:
            # Anonymous memory map
            self.mm = mmap.mmap(-1, size)

    @property
    def buffer(self) -> memoryview:
        """Returns a zero-copy memoryview of the mapped memory."""
        return memoryview(self.mm)

    def flush(self):
        """Write changes in the memory map to the backing storage."""
        if self.mm is not None:
            self.mm.flush()


    def close(self):
        """Release and close mmap resources."""
        if hasattr(self, "mm") and self.mm is not None:
            self.mm.close()
            self.mm = None
        if hasattr(self, "file_obj") and self.file_obj is not None:
            self.file_obj.close()
            self.file_obj = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
