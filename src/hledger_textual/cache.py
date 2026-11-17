"""Thread-safe cache for hledger subprocess results."""

from __future__ import annotations

import glob
import re
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any

_INCLUDE_RE = re.compile(r"^\s*include\s+(?P<path>[^;]+?)\s*(?:;.*)?$")
_MAX_INCLUDE_FILES = 256

# Parsed include lists keyed by (path, mtime_ns, size).  Journal files rarely
# change, so this avoids re-reading the whole journal on every cache lookup
# while still picking up include edits.  Shared by the in-memory and on-disk
# caches.
_INCLUDE_CACHE: dict[tuple[str, int, int], tuple[Path, ...]] = {}
_INCLUDE_LOCK = threading.Lock()


def _stat_entry(path: Path) -> tuple[str, int, int]:
    """Return a stable (path, mtime_ns, size) tuple for *path*.

    Missing files use ``-1`` for both numbers so that creating the file
    changes the signature.

    Args:
        path: File to stat.

    Returns:
        A ``(path, mtime_ns, size)`` tuple.
    """
    try:
        stat = path.stat()
    except OSError:
        return (str(path), -1, -1)
    return (str(path), stat.st_mtime_ns, stat.st_size)


def _included_files(path: Path) -> tuple[Path, ...]:
    """Return the files directly included by *path*.

    Supports quoted paths, ``~`` expansion, paths relative to the including
    file, trailing comments, and glob patterns.

    Args:
        path: Journal file to inspect.

    Returns:
        A tuple of include targets, or an empty tuple when the file cannot be
        read or declares no includes.
    """
    entry = _stat_entry(path)
    key = (entry[0], entry[1], entry[2])
    with _INCLUDE_LOCK:
        cached = _INCLUDE_CACHE.get(key)
    if cached is not None:
        return cached

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ()

    includes: list[Path] = []
    for line in text.splitlines():
        match = _INCLUDE_RE.match(line)
        if match is None:
            continue
        raw = match.group("path").strip().strip('"').strip("'")
        if not raw:
            continue
        target = Path(raw).expanduser()
        if not target.is_absolute():
            target = path.parent / target
        if glob.has_magic(str(target)):
            matches = sorted(glob.glob(str(target)))
        else:
            matches = [str(target)]
        includes.extend(Path(match) for match in matches)

    result = tuple(includes)
    with _INCLUDE_LOCK:
        _INCLUDE_CACHE[key] = result
    return result


def journal_signature(
    file: str | Path | None,
    extra_files: Sequence[str | Path] = (),
) -> tuple[tuple[str, int, int], ...]:
    """Build a cache signature from the journal and its includes.

    Args:
        file: Main journal file, or None.
        extra_files: Additional files whose mtime must be tracked (for
            example a price database).

    Returns:
        A sorted tuple of ``(path, mtime_ns, size)`` entries.
    """
    entries: list[tuple[str, int, int]] = []

    if file is not None:
        pending = [Path(file).expanduser()]
        seen: set[str] = set()
        while pending and len(seen) < _MAX_INCLUDE_FILES:
            current = pending.pop()
            key = str(current)
            if key in seen:
                continue
            seen.add(key)
            entries.append(_stat_entry(current))
            pending.extend(_included_files(current))

    for extra in extra_files:
        entries.append(_stat_entry(Path(extra).expanduser()))

    return tuple(sorted(entries))


class HledgerCache:
    """Thread-safe cache keyed by (args, journal signature).

    Stores the results of hledger CLI calls and returns cached values when the
    same arguments are used and none of the journal files have been modified
    since the last call.  The signature covers the main journal as well as
    every file reached through ``include`` directives (including glob
    includes), so editing an included file invalidates the cache too.
    """

    def __init__(self) -> None:
        """Initialize an empty cache."""
        self._lock = threading.Lock()
        self._store: dict[tuple, Any] = {}

    # ------------------------------------------------------------------
    # Journal signature
    # ------------------------------------------------------------------

    @staticmethod
    def _stat_entry(path: Path) -> tuple[str, int, int]:
        """Return a stable (path, mtime_ns, size) tuple for *path*."""
        return _stat_entry(path)

    def _included_files(self, path: Path) -> tuple[Path, ...]:
        """Return the files directly included by *path*."""
        return _included_files(path)

    def _signature(
        self,
        file: str | Path | None,
        extra_files: Sequence[str | Path] = (),
    ) -> tuple[tuple[str, int, int], ...]:
        """Build a cache signature from the journal and its includes."""
        return journal_signature(file, extra_files)

    # ------------------------------------------------------------------
    # Store API
    # ------------------------------------------------------------------

    def get(
        self,
        args: tuple,
        file: str | Path | None = None,
        extra_files: Sequence[str | Path] = (),
    ) -> Any | None:
        """Return a cached result, or ``None`` on miss.

        Args:
            args: The hledger argument tuple used as cache key.
            file: Path to the journal file (signature is checked).
            extra_files: Additional files whose mtime invalidates the entry.

        Returns:
            The cached result, or ``None`` if not found or stale.
        """
        key = (args, self._signature(file, extra_files))
        with self._lock:
            return self._store.get(key)

    def put(
        self,
        args: tuple,
        result: Any,
        file: str | Path | None = None,
        extra_files: Sequence[str | Path] = (),
    ) -> None:
        """Store a result in the cache.

        Args:
            args: The hledger argument tuple used as cache key.
            result: The value to cache.
            file: Path to the journal file (signature is recorded).
            extra_files: Additional files whose mtime invalidates the entry.
        """
        key = (args, self._signature(file, extra_files))
        with self._lock:
            self._store[key] = result

    def invalidate_all(self) -> None:
        """Clear the entire cache."""
        with self._lock:
            self._store.clear()

    def __len__(self) -> int:
        """Return the number of cached entries."""
        with self._lock:
            return len(self._store)
