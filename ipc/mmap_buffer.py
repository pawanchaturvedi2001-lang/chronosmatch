"""Fixed-size memory-mapped storage for ChronosMatch."""

import mmap
import os
from typing import Optional


class MmapBuffer:
    """Memory-mapped storage backed by a file or anonymous memory."""

    def __init__(
        self,
        filepath: Optional[str] = None,
        size: int = 10 * 1024 * 1024,
        create: bool = True,
    ):
        if size <= 0:
            raise ValueError("Buffer size must be positive")

        self.size = size
        self.filepath = filepath
        self.file_obj = None
        self.mm = None
        self._mv = None

        try:
            if filepath is not None:
                parent = os.path.dirname(os.path.abspath(filepath))
                os.makedirs(parent, exist_ok=True)

                if create:
                    with open(filepath, "a+b") as file_obj:
                        file_obj.truncate(size)

                if not os.path.exists(filepath):
                    raise FileNotFoundError(filepath)

                self.file_obj = open(filepath, "r+b")
                actual_size = os.fstat(self.file_obj.fileno()).st_size

                if actual_size < size:
                    raise ValueError(
                        f"Backing file is {actual_size} bytes; "
                        f"{size} bytes are required"
                    )

                self.mm = mmap.mmap(
                    self.file_obj.fileno(),
                    size,
                    access=mmap.ACCESS_WRITE,
                )
            else:
                self.mm = mmap.mmap(-1, size)

            self._mv = memoryview(self.mm)

        except Exception:
            self.close()
            raise

    @property
    def buffer(self) -> memoryview:
        """Return a memoryview of the mapped bytes."""
        if self._mv is None:
            raise ValueError("Buffer is closed")
        return self._mv

    def flush(self) -> None:
        """Flush changes to file-backed storage."""
        if self.mm is None:
            raise ValueError("Buffer is closed")
        if self.filepath is not None:
            self.mm.flush()

    def close(self) -> None:
        """Release the memoryview, mapping, and backing file."""
        if self._mv is not None:
            self._mv.release()
            self._mv = None

        if self.mm is not None:
            self.mm.close()
            self.mm = None

        if self.file_obj is not None:
            self.file_obj.close()
            self.file_obj = None

    def __enter__(self):
        if self._mv is None:
            raise ValueError("Buffer is closed")
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False
