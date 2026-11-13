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
#   write_idx: uint64 (8 bytes, offset 0)
#   read_idx:  uint64 (8 bytes, offset 8)
#   capacity:  uint32 (4 bytes, offset 16)
#   slot_size: uint32 (4 bytes, offset 20)
HEADER_FORMAT = "<QQII"
HEADER_STRUCT = struct.Struct(HEADER_FORMAT)
HEADER_SIZE = HEADER_STRUCT.size  # 24 bytes

# Dedicated sub-structs for atomic independent index updates:
# Producer updates ONLY write_idx (offset 0); Consumer updates ONLY read_idx (offset 8).
# This prevents race conditions where unpacking and packing the full header rewrites stale indices.
WRITE_IDX_STRUCT = struct.Struct("<Q")
WRITE_IDX_OFFSET = 0

READ_IDX_STRUCT = struct.Struct("<Q")
READ_IDX_OFFSET = 8

PARAMS_STRUCT = struct.Struct("<II")
PARAMS_OFFSET = 16


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
            # Initialize complete header: write_idx=0, read_idx=0, capacity, slot_size
            HEADER_STRUCT.pack_into(self._mv, 0, 0, 0, self.capacity, self.slot_size)
        else:
            # Read header parameters
            w, r, cap, sz = HEADER_STRUCT.unpack_from(self._mv, 0)
            self.capacity = cap
            self.slot_size = sz

    @property
    def write_idx(self) -> int:
        """Current monotonic write index."""
        return WRITE_IDX_STRUCT.unpack_from(self._mv, WRITE_IDX_OFFSET)[0]

    @write_idx.setter
    def write_idx(self, value: int):
        WRITE_IDX_STRUCT.pack_into(self._mv, WRITE_IDX_OFFSET, value)

    @property
    def read_idx(self) -> int:
        """Current monotonic read index."""
        return READ_IDX_STRUCT.unpack_from(self._mv, READ_IDX_OFFSET)[0]

    @read_idx.setter
    def read_idx(self, value: int):
        READ_IDX_STRUCT.pack_into(self._mv, READ_IDX_OFFSET, value)

    def size(self) -> int:
        """Returns the number of unconsumed items currently in the buffer."""
        w = WRITE_IDX_STRUCT.unpack_from(self._mv, WRITE_IDX_OFFSET)[0]
        r = READ_IDX_STRUCT.unpack_from(self._mv, READ_IDX_OFFSET)[0]
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

        Single-Producer Single-Consumer (SPSC) safe:
        - Reads read_idx to verify available capacity.
        - Copies payload into slot BEFORE advancing write_idx.
        - Updates ONLY write_idx at offset 0 (never touches read_idx at offset 8).

        Args:
            data: Binary payload of length <= slot_size.

        Returns:
            True if written successfully, False if buffer is full.
        """
        w = WRITE_IDX_STRUCT.unpack_from(self._mv, WRITE_IDX_OFFSET)[0]
        r = READ_IDX_STRUCT.unpack_from(self._mv, READ_IDX_OFFSET)[0]
        cap = self.capacity
        slot_sz = self.slot_size

        if w - r >= cap:
            return False  # Buffer full

        data_len = len(data)
        if data_len > slot_sz:
            raise ValueError(f"Data size {data_len} exceeds slot size {slot_sz}")

        slot_offset = HEADER_SIZE + ((w % cap) * slot_sz)
        self._mv[slot_offset : slot_offset + data_len] = data

        # Advance ONLY write index at offset 0
        WRITE_IDX_STRUCT.pack_into(self._mv, WRITE_IDX_OFFSET, w + 1)
        return True

    def read(self) -> Optional[bytes]:
        """
        Read the next binary item from the ring buffer.

        Single-Producer Single-Consumer (SPSC) safe:
        - Reads write_idx to verify available items.
        - Copies payload out of slot BEFORE advancing read_idx.
        - Updates ONLY read_idx at offset 8 (never touches write_idx at offset 0).

        Returns:
            bytes containing the slot payload, or None if the buffer is empty.
        """
        r = READ_IDX_STRUCT.unpack_from(self._mv, READ_IDX_OFFSET)[0]
        w = WRITE_IDX_STRUCT.unpack_from(self._mv, WRITE_IDX_OFFSET)[0]
        cap = self.capacity
        slot_sz = self.slot_size

        if r >= w:
            return None  # Buffer empty

        slot_offset = HEADER_SIZE + ((r % cap) * slot_sz)
        data = bytes(self._mv[slot_offset : slot_offset + slot_sz])

        # Advance ONLY read index at offset 8
        READ_IDX_STRUCT.pack_into(self._mv, READ_IDX_OFFSET, r + 1)
        return data

    def reset(self):
        """Reset write and read indices to 0."""
        WRITE_IDX_STRUCT.pack_into(self._mv, WRITE_IDX_OFFSET, 0)
        READ_IDX_STRUCT.pack_into(self._mv, READ_IDX_OFFSET, 0)

    def close(self):
        """Release underlying mmap buffer."""
        if hasattr(self, "_mv") and self._mv is not None:
            self._mv.release()
            self._mv = None
        if hasattr(self, "_mmap_buf") and self._mmap_buf is not None:
            self._mmap_buf.close()
            self._mmap_buf = None
