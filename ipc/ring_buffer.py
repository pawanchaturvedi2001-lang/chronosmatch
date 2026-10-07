"""
ChronosMatch Zero-Copy High-Frequency Trading Engine
IPC Ring Buffer module (Member 2)

High-performance lock-free Single-Producer Single-Consumer (SPSC) ring buffer
stored directly in memory-mapped shared memory.
"""

import struct
from typing import Optional
from ipc.structures import ORDER_SIZE
from ipc.mmap_buffer import MmapBuffer


class BufferFullError(Exception):
    """Raised or used when the ring buffer has reached capacity."""
    pass


# Ring buffer header format:
# '<QQII' (24 bytes):
#   write_idx: uint64 (8 bytes)
#   read_idx:  uint64 (8 bytes)
#   capacity:  uint32 (4 bytes)
#   slot_size: uint32 (4 bytes)
HEADER_FORMAT = "<QQII"
HEADER_STRUCT = struct.Struct(HEADER_FORMAT)
HEADER_SIZE = HEADER_STRUCT.size  # 24 bytes


class RingBuffer:
    """
    Fixed-slot, zero-copy circular ring buffer implemented over shared memory.

    Layout in shared memory:
    [ HEADER (24 bytes) ] [ SLOT 0 (slot_size) ] [ SLOT 1 ] ... [ SLOT capacity-1 ]
    """

    def __init__(
        self,
        capacity: int = 65536,
        slot_size: int = ORDER_SIZE,
        mmap_buffer: Optional[MmapBuffer] = None,
        filepath: Optional[str] = None,
        create: bool = True,
    ):
        """
        Initialize the RingBuffer.

        Args:
            capacity: Total number of slots (orders) the ring buffer can store.
            slot_size: Size in bytes of each slot (defaults to ORDER_SIZE = 29 bytes).
            mmap_buffer: Optional existing MmapBuffer instance.
            filepath: Optional file path if creating a new file-backed shared buffer.
            create: Whether this instance initializes header state.
        """
        self.capacity = capacity
        self.slot_size = slot_size
        total_size = HEADER_SIZE + (capacity * slot_size)

        if mmap_buffer is not None:
            self._mmap_buf = mmap_buffer
        else:
            self._mmap_buf = MmapBuffer(filepath=filepath, size=total_size, create=create)

        self._mv = self._mmap_buf.buffer

        if create:
            # Initialize header: write_idx=0, read_idx=0, capacity, slot_size
            HEADER_STRUCT.pack_into(self._mv, 0, 0, 0, self.capacity, self.slot_size)
        else:
            # Read header parameters
            w, r, cap, sz = HEADER_STRUCT.unpack_from(self._mv, 0)
            self.capacity = cap
            self.slot_size = sz

    @property
    def write_idx(self) -> int:
        """Current monotonic write index."""
        return HEADER_STRUCT.unpack_from(self._mv, 0)[0]

    @write_idx.setter
    def write_idx(self, value: int):
        HEADER_STRUCT.pack_into(
            self._mv, 0,
            value,
            self.read_idx,
            self.capacity,
            self.slot_size,
        )

    @property
    def read_idx(self) -> int:
        """Current monotonic read index."""
        return HEADER_STRUCT.unpack_from(self._mv, 0)[1]

    @read_idx.setter
    def read_idx(self, value: int):
        HEADER_STRUCT.pack_into(
            self._mv, 0,
            self.write_idx,
            value,
            self.capacity,
            self.slot_size,
        )

    def size(self) -> int:
        """Returns the number of unconsumed items currently in the buffer."""
        w, r, _, _ = HEADER_STRUCT.unpack_from(self._mv, 0)
        return w - r

    def is_full(self) -> bool:
        """Returns True if the buffer cannot accept any more items."""
        return self.size() >= self.capacity

    def is_empty(self) -> bool:
        """Returns True if there are no items waiting to be read."""
        return self.size() == 0

    def available_write(self) -> int:
        """Number of free slots available for writing."""
        return max(0, self.capacity - self.size())

    def available_read(self) -> int:
        """Number of items available for reading."""
        return self.size()

    def write(self, data: bytes) -> bool:
        """
        Write binary data into the next free slot in the ring buffer.

        Args:
            data: Binary payload of length <= slot_size.

        Returns:
            True if written successfully, False if buffer is full.
        """
        w, r, cap, slot_sz = HEADER_STRUCT.unpack_from(self._mv, 0)
        if w - r >= cap:
            return False  # Buffer full

        slot_offset = HEADER_SIZE + ((w % cap) * slot_sz)
        data_len = len(data)
        if data_len > slot_sz:
            raise ValueError(f"Data size {data_len} exceeds slot size {slot_sz}")

        self._mv[slot_offset : slot_offset + data_len] = data

        # Advance write index
        HEADER_STRUCT.pack_into(self._mv, 0, w + 1, r, cap, slot_sz)
        return True

    def read(self) -> Optional[bytes]:
        """
        Read the next binary item from the ring buffer.

        Returns:
            bytes containing the slot payload, or None if the buffer is empty.
        """
        w, r, cap, slot_sz = HEADER_STRUCT.unpack_from(self._mv, 0)
        if r >= w:
            return None  # Buffer empty

        slot_offset = HEADER_SIZE + ((r % cap) * slot_sz)
        data = bytes(self._mv[slot_offset : slot_offset + slot_sz])

        # Advance read index
        HEADER_STRUCT.pack_into(self._mv, 0, w, r + 1, cap, slot_sz)
        return data

    def reset(self):
        """Reset write and read indices to 0."""
        HEADER_STRUCT.pack_into(self._mv, 0, 0, 0, self.capacity, self.slot_size)

    def close(self):
        """Release underlying mmap buffer."""
        if hasattr(self, "_mv") and self._mv is not None:
            self._mv.release()
            self._mv = None
        if hasattr(self, "_mmap_buf") and self._mmap_buf is not None:
            self._mmap_buf.close()
            self._mmap_buf = None
