import pytest

from ipc.mmap_buffer import MmapBuffer
from ipc.structures import ORDER_SIZE


def test_anonymous_buffer_write_and_read():
    with MmapBuffer(size=ORDER_SIZE) as buffer:
        payload = bytes(range(ORDER_SIZE))
        buffer.buffer[:ORDER_SIZE] = payload
        assert bytes(buffer.buffer[:ORDER_SIZE]) == payload


def test_file_backed_buffer_persists_data(tmp_path):
    path = str(tmp_path / "mmap_test.bin")
    payload = b"A" * ORDER_SIZE

    with MmapBuffer(filepath=path, size=ORDER_SIZE) as buffer:
        buffer.buffer[:ORDER_SIZE] = payload
        buffer.flush()

    with MmapBuffer(filepath=path, size=ORDER_SIZE, create=False) as buffer:
        assert bytes(buffer.buffer[:ORDER_SIZE]) == payload


def test_buffer_has_expected_size():
    with MmapBuffer(size=ORDER_SIZE) as buffer:
        assert len(buffer.buffer) == ORDER_SIZE


def test_close_releases_buffer():
    buffer = MmapBuffer(size=ORDER_SIZE)
    buffer.close()
    assert buffer._mv is None
    assert buffer.mm is None


def test_file_backed_buffer_creates_parent_directory(tmp_path):
    path = str(tmp_path / "nested" / "mmap_test.bin")

    with MmapBuffer(filepath=path, size=ORDER_SIZE) as buffer:
        buffer.buffer[0] = 42
        buffer.flush()

    assert (tmp_path / "nested" / "mmap_test.bin").exists()


def test_closed_buffer_rejects_access():
    buffer = MmapBuffer(size=ORDER_SIZE)
    buffer.close()

    with pytest.raises(ValueError):
        _ = buffer.buffer
