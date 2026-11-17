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


def test_file_mtime_none_returns_empty_signature():
    """A None journal produces an empty signature without touching the filesystem."""
    from hledger_textual.cache import HledgerCache

    assert HledgerCache()._signature(None) == ()


def test_file_mtime_missing_file_returns_negative(tmp_path):
    """Missing files get a stable -1 signature entry (OSError branch)."""
    from hledger_textual.cache import HledgerCache

    missing = tmp_path / "nope.journal"
    assert HledgerCache()._signature(missing) == ((str(missing), -1, -1),)


def test_included_file_change_invalidates(tmp_path):
    """Editing a file reached through ``include`` invalidates cached values."""
    main = tmp_path / "main.journal"
    child = tmp_path / "child.journal"
    child.write_text("2025-01-01 first\n", encoding="utf-8")
    main.write_text("include child.journal\n", encoding="utf-8")

    cache = HledgerCache()
    cache.put(("print",), "old", file=main)
    assert cache.get(("print",), file=main) == "old"

    # Change the size as well as the mtime so coarse filesystems still differ.
    child.write_text("2025-01-02 second\n" * 10, encoding="utf-8")
    assert cache.get(("print",), file=main) is None


def test_nested_include_change_invalidates(tmp_path):
    """Includes are followed recursively."""
    main = tmp_path / "main.journal"
    middle = tmp_path / "middle.journal"
    leaf = tmp_path / "leaf.journal"
    leaf.write_text("2025-01-01 leaf\n", encoding="utf-8")
    middle.write_text("include leaf.journal\n", encoding="utf-8")
    main.write_text("include middle.journal\n", encoding="utf-8")

    cache = HledgerCache()
    cache.put(("print",), "old", file=main)
    leaf.write_text("2025-01-02 changed leaf\n" * 5, encoding="utf-8")
    assert cache.get(("print",), file=main) is None


def test_glob_include_change_invalidates(tmp_path):
    """Glob include targets are part of the journal signature."""
    (tmp_path / "sub").mkdir()
    child = tmp_path / "sub" / "2025.journal"
    child.write_text("2025-01-01 first\n", encoding="utf-8")
    main = tmp_path / "main.journal"
    main.write_text("include sub/*.journal\n", encoding="utf-8")

    cache = HledgerCache()
    cache.put(("print",), "old", file=main)
    child.write_text("2025-01-02 second\n" * 4, encoding="utf-8")
    assert cache.get(("print",), file=main) is None


def test_extra_file_change_invalidates(tmp_path):
    """Extra files (e.g. a price database) participate in invalidation."""
    journal = tmp_path / "main.journal"
    journal.write_text("2025-01-01 x\n", encoding="utf-8")
    prices = tmp_path / "prices.journal"
    prices.write_text("P 2025-01-01 EUR 1\n", encoding="utf-8")

    cache = HledgerCache()
    cache.put(("bal",), "old", file=journal, extra_files=[prices])
    assert cache.get(("bal",), file=journal, extra_files=[prices]) == "old"

    prices.write_text("P 2025-01-02 EUR 1.1\n" * 3, encoding="utf-8")
    assert cache.get(("bal",), file=journal, extra_files=[prices]) is None


def test_include_cycle_does_not_loop(tmp_path):
    """Mutually including journals terminate."""
    first = tmp_path / "a.journal"
    second = tmp_path / "b.journal"
    first.write_text("include b.journal\n", encoding="utf-8")
    second.write_text("include a.journal\n", encoding="utf-8")

    cache = HledgerCache()
    cache.put(("print",), "value", file=first)
    assert cache.get(("print",), file=first) == "value"
