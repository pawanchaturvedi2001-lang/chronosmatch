"""Memory-mapped FIFO ring buffer for ChronosMatch."""

import struct
from typing import Optional

from ipc.mmap_buffer import MmapBuffer
from ipc.structures import ORDER_SIZE

HEADER_FORMAT = "<QQII"
HEADER_STRUCT = struct.Struct(HEADER_FORMAT)
HEADER_SIZE = HEADER_STRUCT.size


class BufferFullError(Exception):
    """Raised when the ring buffer is full."""


class RingBuffer:
    """Fixed-capacity FIFO ring buffer using memory-mapped storage."""

    def __init__(
        self,
        capacity: int = 65536,
        slot_size: int = ORDER_SIZE,
        mmap_buffer: Optional[MmapBuffer] = None,
        filepath: Optional[str] = None,
        create: bool = True,
    ):
        if capacity <= 0:
            raise ValueError("Capacity must be positive")
        if slot_size <= 0:
            raise ValueError("Slot size must be positive")

        self.capacity = capacity
        self.slot_size = slot_size
        self._owns_buffer = mmap_buffer is None
        self._mmap_buf = None
        self._mv = None

        total_size = HEADER_SIZE + capacity * slot_size

        try:
            if mmap_buffer is not None:
                self._mmap_buf = mmap_buffer
            else:
                self._mmap_buf = MmapBuffer(
                    filepath=filepath,
                    size=total_size,
                    create=create,
                )

            self._mv = self._mmap_buf.buffer

            if create:
                HEADER_STRUCT.pack_into(
                    self._mv, 0, 0, 0, capacity, slot_size
                )
            else:
                _, _, saved_capacity, saved_slot_size = (
                    HEADER_STRUCT.unpack_from(self._mv, 0)
                )

                if saved_capacity <= 0 or saved_slot_size <= 0:
                    raise ValueError("Invalid ring buffer header")

                if saved_capacity != capacity:
                    raise ValueError("Saved capacity does not match")

                if saved_slot_size != slot_size:
                    raise ValueError("Saved slot size does not match")

            required_size = HEADER_SIZE + capacity * slot_size
            if len(self._mv) < required_size:
                raise ValueError("Mapped buffer is too small")

        except Exception:
            self.close()
            raise

    def _header(self):
        return HEADER_STRUCT.unpack_from(self._mv, 0)

    @property
    def write_idx(self) -> int:
        return self._header()[0]

    @property
    def read_idx(self) -> int:
        return self._header()[1]

    @property
    def size(self) -> int:
        write_idx, read_idx, _, _ = self._header()
        return write_idx - read_idx

    @property
    def available_write(self) -> int:
        return self.capacity - self.size

    @property
    def available_read(self) -> int:
        return self.size

    def is_empty(self) -> bool:
        return self.size == 0

    def is_full(self) -> bool:
        return self.size >= self.capacity

    def write(self, data: bytes) -> bool:
        if self._mv is None:
            raise ValueError("Ring buffer is closed")

        if len(data) != self.slot_size:
            raise ValueError(
                f"Record must be exactly {self.slot_size} bytes"
            )

        write_idx, read_idx, capacity, slot_size = self._header()

        if write_idx - read_idx >= capacity:
            return False

        offset = HEADER_SIZE + (write_idx % capacity) * slot_size
        self._mv[offset:offset + slot_size] = data

        HEADER_STRUCT.pack_into(
            self._mv, 0,
            write_idx + 1, read_idx, capacity, slot_size,
        )
        return True

    def read(self) -> Optional[bytes]:
        if self._mv is None:
            raise ValueError("Ring buffer is closed")

        write_idx, read_idx, capacity, slot_size = self._header()

        if read_idx >= write_idx:
            return None

        offset = HEADER_SIZE + (read_idx % capacity) * slot_size
        data = bytes(self._mv[offset:offset + slot_size])

        HEADER_STRUCT.pack_into(
            self._mv, 0,
            write_idx, read_idx + 1, capacity, slot_size,
        )
        return data

    def reset(self):
        if self._mv is None:
            raise ValueError("Ring buffer is closed")

        _, _, capacity, slot_size = self._header()
        HEADER_STRUCT.pack_into(
            self._mv, 0, 0, 0, capacity, slot_size
        )

    def flush(self):
        if self._mmap_buf is None:
            raise ValueError("Ring buffer is closed")
        self._mmap_buf.flush()

    def close(self):
        if self._mv is not None:
            self._mv.release()
            self._mv = None

        if self._owns_buffer and self._mmap_buf is not None:
            self._mmap_buf.close()

        self._mmap_buf = None

    def __enter__(self):
        if self._mv is None:
            raise ValueError("Ring buffer is closed")
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False