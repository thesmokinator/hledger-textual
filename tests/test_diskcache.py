"""Tests for the persistent hledger output cache (issue #162)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hledger_textual import diskcache
from hledger_textual.diskcache import HledgerDiskCache, disk_cache_enabled


@pytest.fixture
def cache(tmp_path: Path, monkeypatch) -> HledgerDiskCache:
    """A disk cache in a temporary directory with the real hledger disabled."""
    monkeypatch.setattr(diskcache, "_hledger_version", lambda: "test-version")
    return HledgerDiskCache(tmp_path / "cache", enabled=True)


def test_put_and_get(cache: HledgerDiskCache, tmp_path: Path):
    """A stored output is returned without touching hledger again."""
    journal = tmp_path / "j.journal"
    journal.write_text("2026-01-01 x\n")
    cache.put(("balance",), "output", file=journal)
    assert cache.get(("balance",), file=journal) == "output"


def test_miss_for_unknown_args(cache: HledgerDiskCache, tmp_path: Path):
    """Different arguments miss the cache."""
    journal = tmp_path / "j.journal"
    journal.write_text("2026-01-01 x\n")
    cache.put(("balance", "type:R"), "output", file=journal)
    assert cache.get(("balance", "type:X"), file=journal) is None


def test_journal_change_invalidates(cache: HledgerDiskCache, tmp_path: Path):
    """Changing the journal mtime/size invalidates the entry."""
    journal = tmp_path / "j.journal"
    journal.write_text("2026-01-01 x\n")
    cache.put(("balance",), "output", file=journal)
    journal.write_text("2026-01-02 changed\n" * 3)
    assert cache.get(("balance",), file=journal) is None


def test_include_change_invalidates(cache: HledgerDiskCache, tmp_path: Path):
    """Editing an included file invalidates the entry."""
    journal = tmp_path / "j.journal"
    child = tmp_path / "child.journal"
    child.write_text("2026-01-01 x\n")
    journal.write_text("include child.journal\n")
    cache.put(("balance",), "output", file=journal)
    child.write_text("2026-01-02 changed\n" * 2)
    assert cache.get(("balance",), file=journal) is None


def test_extra_file_change_invalidates(cache: HledgerDiskCache, tmp_path: Path):
    """A prices file passed with -f participates in the key."""
    journal = tmp_path / "j.journal"
    prices = tmp_path / "prices.journal"
    journal.write_text("2026-01-01 x\n")
    prices.write_text("P 2026-01-01 EUR 1\n")
    cache.put(("balance", "-V"), "output", file=journal, extra_files=[prices])
    prices.write_text("P 2026-01-02 EUR 1.1\n" * 3)
    assert cache.get(("balance", "-V"), file=journal, extra_files=[prices]) is None


def test_disabled_cache(cache: HledgerDiskCache, tmp_path: Path):
    """A disabled cache never stores or returns values."""
    journal = tmp_path / "j.journal"
    journal.write_text("2026-01-01 x\n")
    disabled = HledgerDiskCache(cache.directory, enabled=False)
    disabled.put(("balance",), "output", file=journal)
    assert disabled.get(("balance",), file=journal) is None


def test_oversized_output_is_skipped(tmp_path: Path, monkeypatch):
    """Output larger than the per-entry limit is not written to disk."""
    monkeypatch.setattr(diskcache, "_hledger_version", lambda: "test-version")
    journal = tmp_path / "j.journal"
    journal.write_text("2026-01-01 x\n")
    cache = HledgerDiskCache(tmp_path / "cache", enabled=True, max_entry_bytes=5)
    cache.put(("print",), "too long", file=journal)
    assert cache.get(("print",), file=journal) is None


def test_corrupt_entry_is_a_miss(cache: HledgerDiskCache, tmp_path: Path):
    """Corrupt JSON does not raise and behaves like a cache miss."""
    journal = tmp_path / "j.journal"
    journal.write_text("2026-01-01 x\n")
    cache.put(("balance",), "output", file=journal)
    entry = next(cache.directory.glob("*.json"))
    entry.write_text("{not json")
    assert cache.get(("balance",), file=journal) is None


def test_clear_removes_entries(cache: HledgerDiskCache, tmp_path: Path):
    """clear() removes every cached file."""
    journal = tmp_path / "j.journal"
    journal.write_text("2026-01-01 x\n")
    cache.put(("balance",), "output", file=journal)
    assert list(cache.directory.glob("*.json"))
    cache.clear()
    assert list(cache.directory.glob("*.json")) == []


def test_pruning_keeps_newest_entries(tmp_path: Path, monkeypatch):
    """Pruning trims the oldest entries once the cap is exceeded."""
    monkeypatch.setattr(diskcache, "_hledger_version", lambda: "test-version")
    journal = tmp_path / "j.journal"
    journal.write_text("2026-01-01 x\n")
    cache = HledgerDiskCache(tmp_path / "cache", enabled=True, max_entries=2)
    for index in range(4):
        cache.put((f"balance-{index}",), "output", file=journal)
    # Force the periodic prune pass without depending on timing.
    cache._puts = 15
    cache.put(("balance-final",), "output", file=journal)
    assert len(list(cache.directory.glob("*.json"))) <= 2


def test_env_flags(monkeypatch):
    """The environment toggles the disk cache and redirects its directory."""
    monkeypatch.delenv("HLEDGER_TEXTUAL_NO_DISK_CACHE", raising=False)
    assert disk_cache_enabled() is True
    monkeypatch.setenv("HLEDGER_TEXTUAL_NO_DISK_CACHE", "1")
    assert disk_cache_enabled() is False
    monkeypatch.setenv("HLEDGER_TEXTUAL_NO_DISK_CACHE", "off")
    assert disk_cache_enabled() is True
    monkeypatch.setenv("HLEDGER_TEXTUAL_NO_DISK_CACHE", "0")
    assert disk_cache_enabled() is True

    monkeypatch.setenv("HLEDGER_TEXTUAL_CACHE_DIR", "/tmp/custom-cache")
    assert diskcache.default_cache_dir() == Path("/tmp/custom-cache")


def test_run_hledger_uses_disk_cache(monkeypatch, tmp_path: Path, cache: HledgerDiskCache):
    """A second identical command is served from the persistent cache."""
    from hledger_textual import hledger as hledger_module

    journal = tmp_path / "j.journal"
    journal.write_text("2026-01-01 x\n")
    calls: list[list[str]] = []

    def _fake_run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(stdout="cached-output\n")

    monkeypatch.setattr(diskcache, "_hledger_version", lambda: "test-version")
    monkeypatch.setattr(hledger_module, "disk_cache", cache)
    monkeypatch.setattr(hledger_module.subprocess, "run", _fake_run)

    assert hledger_module.run_hledger("balance", file=journal) == "cached-output\n"
    assert hledger_module.run_hledger("balance", file=journal) == "cached-output\n"
    assert len(calls) == 1

    journal.write_text("2026-01-02 changed\n" * 2)
    assert hledger_module.run_hledger("balance", file=journal) == "cached-output\n"
    assert len(calls) == 2


def test_version_command_is_not_disk_cached(monkeypatch, tmp_path: Path, cache: HledgerDiskCache):
    """--version bypasses the cache so the cache key can obtain a version."""
    from hledger_textual import hledger as hledger_module

    calls: list[list[str]] = []

    def _fake_run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(stdout="hledger 9.9\n")

    monkeypatch.setattr(hledger_module, "disk_cache", cache)
    monkeypatch.setattr(hledger_module.subprocess, "run", _fake_run)
    hledger_module.run_hledger("--version")
    hledger_module.run_hledger("--version")
    assert len(calls) == 2


def test_mutating_commands_bypass_disk_cache(
    monkeypatch, tmp_path: Path, cache: HledgerDiskCache
):
    """import/add must always run, even with an unchanged journal."""
    from hledger_textual import hledger as hledger_module

    journal = tmp_path / "j.journal"
    journal.write_text("2026-01-01 x\n")
    calls: list[list[str]] = []

    def _fake_run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(hledger_module, "disk_cache", cache)
    monkeypatch.setattr(hledger_module.subprocess, "run", _fake_run)
    hledger_module.run_hledger("import", file=journal)
    hledger_module.run_hledger("import", file=journal)
    hledger_module.run_hledger("add", file=journal)
    assert len(calls) == 3
