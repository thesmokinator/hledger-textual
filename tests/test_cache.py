"""Unit tests for HledgerCache (no hledger needed)."""

from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path

from hledger_textual.cache import HledgerCache


def test_get_returns_none_on_miss():
    """A fresh cache returns None for any key."""
    cache = HledgerCache()
    assert cache.get(("print", "-O", "json")) is None


def test_put_and_get_hit():
    """A cached value is returned on a subsequent get."""
    cache = HledgerCache()
    args = ("balance", "--flat")
    result = [("assets:bank", "€100.00")]
    cache.put(args, result)
    assert cache.get(args) == result


def test_invalidate_all_clears_cache():
    """invalidate_all removes all entries."""
    cache = HledgerCache()
    cache.put(("a",), "val1")
    cache.put(("b",), "val2")
    assert len(cache) == 2
    cache.invalidate_all()
    assert len(cache) == 0
    assert cache.get(("a",)) is None


def test_mtime_invalidation():
    """Changing the file mtime invalidates old entries."""
    with tempfile.NamedTemporaryFile(suffix=".journal", delete=False) as f:
        f.write(b"2025-01-01 test\n")
        path = Path(f.name)

    cache = HledgerCache()
    args = ("print",)
    cache.put(args, "old_result", file=path)
    assert cache.get(args, file=path) == "old_result"

    # Modify the file to change mtime
    time.sleep(0.05)
    path.write_text("2025-01-02 updated\n")

    # Old cache entry is now stale
    assert cache.get(args, file=path) is None

    # Clean up
    path.unlink()


def test_different_args_different_entries():
    """Different argument tuples produce separate cache entries."""
    cache = HledgerCache()
    cache.put(("a",), "val_a")
    cache.put(("b",), "val_b")
    assert cache.get(("a",)) == "val_a"
    assert cache.get(("b",)) == "val_b"
    assert len(cache) == 2


def test_thread_safety():
    """Concurrent put/get from multiple threads does not crash."""
    cache = HledgerCache()
    errors: list[Exception] = []

    def writer(tid: int) -> None:
        try:
            for i in range(50):
                cache.put((f"t{tid}", str(i)), f"result-{tid}-{i}")
        except Exception as e:
            errors.append(e)

    def reader(tid: int) -> None:
        try:
            for i in range(50):
                cache.get((f"t{tid}", str(i)))
        except Exception as e:
            errors.append(e)

    threads = []
    for tid in range(4):
        threads.append(threading.Thread(target=writer, args=(tid,)))
        threads.append(threading.Thread(target=reader, args=(tid,)))

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors


def test_len():
    """__len__ reflects the number of entries."""
    cache = HledgerCache()
    assert len(cache) == 0
    cache.put(("x",), 1)
    assert len(cache) == 1
    cache.put(("y",), 2)
    assert len(cache) == 2


def test_none_file():
    """Cache works with file=None (no mtime check)."""
    cache = HledgerCache()
    args = ("stats",)
    cache.put(args, "stats_result", file=None)
    assert cache.get(args, file=None) == "stats_result"


def test_file_mtime_none_returns_zero():
    """_file_mtime(None) returns 0.0 without touching the filesystem."""
    from hledger_textual.cache import HledgerCache

    assert HledgerCache()._file_mtime(None) == 0.0


def test_file_mtime_missing_file_returns_zero(tmp_path):
    """_file_mtime of a nonexistent path returns 0.0 (OSError branch)."""
    from hledger_textual.cache import HledgerCache

    assert HledgerCache()._file_mtime(tmp_path / "nope.journal") == 0.0
