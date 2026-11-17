"""On-disk cache for raw hledger output.

The in-memory :class:`hledger_textual.cache.HledgerCache` avoids repeated
subprocess calls within one app session.  This module adds a persistent layer
so reopening the app on an unchanged journal does not re-parse it with hledger
on every start.

Entries are keyed by the hledger arguments, the journal signature (main file
plus every ``include``) and the hledger version.  Only successful stdout is
stored; outputs larger than ``max_entry_bytes`` are skipped so a full-journal
``print`` cannot fill the cache directory.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from hledger_textual.cache import journal_signature

#: Bump when the cached payload format or parsing contract changes.
CACHE_VERSION = 1

#: A single command output larger than this is not persisted.  The transactions
#: pane's month query usually fits; a full-journal ``print -O json`` does not.
DEFAULT_MAX_ENTRY_BYTES = 8 * 1024 * 1024

#: Soft limit on the number of entries; the oldest are pruned first.
DEFAULT_MAX_ENTRIES = 512

#: Soft limit on total cache bytes; the oldest entries are pruned first.
DEFAULT_MAX_BYTES = 128 * 1024 * 1024

_TRUE_VALUES = {"1", "true", "yes", "on"}


def default_cache_dir() -> Path:
    """Return the platform cache directory for hledger-textual.

    ``HLEDGER_TEXTUAL_CACHE_DIR`` overrides the location.  ``XDG_CACHE_HOME``
    is honoured on Linux; macOS uses ``~/Library/Caches`` and Windows
    ``%LOCALAPPDATA%``.
    """
    override = os.environ.get("HLEDGER_TEXTUAL_CACHE_DIR")
    if override:
        return Path(override).expanduser()

    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    elif os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "hledger-textual"


def disk_cache_enabled() -> bool:
    """Return False when ``HLEDGER_TEXTUAL_NO_DISK_CACHE`` disables the cache."""
    value = os.environ.get("HLEDGER_TEXTUAL_NO_DISK_CACHE")
    if value is None:
        return True
    return value.strip().lower() not in _TRUE_VALUES


_VERSION: str | None = None
_VERSION_LOCK = threading.Lock()


def _hledger_version() -> str:
    """Return the hledger version used in cache keys, or an empty string."""
    global _VERSION
    with _VERSION_LOCK:
        if _VERSION is not None:
            return _VERSION
        try:
            result = subprocess.run(
                ["hledger", "--version"],
                capture_output=True,
                text=True,
                check=True,
                encoding="utf-8",
                timeout=5,
            )
            _VERSION = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
        except (OSError, subprocess.SubprocessError):
            _VERSION = ""
        return _VERSION


class HledgerDiskCache:
    """Persist raw hledger stdout in a directory of JSON files."""

    def __init__(
        self,
        directory: str | Path | None = None,
        *,
        enabled: bool | None = None,
        max_entry_bytes: int = DEFAULT_MAX_ENTRY_BYTES,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        max_bytes: int = DEFAULT_MAX_BYTES,
    ) -> None:
        """Initialize the cache.

        Args:
            directory: Cache directory; defaults to :func:`default_cache_dir`.
            enabled: Override the environment-based enabled flag.
            max_entry_bytes: Largest stdout value persisted per entry.
            max_entries: Soft cap before the oldest entries are pruned.
            max_bytes: Soft cap on total cache size before pruning.
        """
        self._directory_override = Path(directory).expanduser() if directory else None
        self._enabled_override = enabled
        self.max_entry_bytes = max_entry_bytes
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self._puts = 0
        self._prune_lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        """Whether the cache is active."""
        if self._enabled_override is not None:
            return self._enabled_override
        return disk_cache_enabled()

    @property
    def directory(self) -> Path:
        """Cache directory in use."""
        return self._directory_override or default_cache_dir()

    # ------------------------------------------------------------------
    # Key / entry helpers
    # ------------------------------------------------------------------

    def _key(
        self,
        args: tuple,
        file: str | Path | None,
        extra_files: Sequence[str | Path],
    ) -> str:
        """Build a stable hash for one hledger invocation."""
        payload = json.dumps(
            {
                "version": CACHE_VERSION,
                "hledger": _hledger_version(),
                "args": list(args),
                "signature": journal_signature(file, extra_files),
                # Relative periods such as "thismonth" and forecast output
                # change with the calendar date even when the journal does not.
                "date": date.today().isoformat(),
                "env": {
                    "ledger_file": os.environ.get("LEDGER_FILE", ""),
                    "lc_all": os.environ.get("LC_ALL", ""),
                    "lang": os.environ.get("LANG", ""),
                },
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _entry_path(self, key: str) -> Path:
        """Return the file holding *key*."""
        return self.directory / f"{key}.json"

    # ------------------------------------------------------------------
    # Store API
    # ------------------------------------------------------------------

    def get(
        self,
        args: tuple,
        file: str | Path | None = None,
        extra_files: Sequence[str | Path] = (),
    ) -> str | None:
        """Return cached stdout, or ``None`` on miss/corruption."""
        if not self.enabled:
            return None
        path = self._entry_path(self._key(args, file, extra_files))
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        stdout = payload.get("stdout") if isinstance(payload, dict) else None
        if not isinstance(stdout, str):
            return None
        # Touch the entry so pruning evicts genuinely cold entries first.
        try:
            path.touch()
        except OSError:
            pass
        return stdout

    def put(
        self,
        args: tuple,
        output: str,
        file: str | Path | None = None,
        extra_files: Sequence[str | Path] = (),
    ) -> None:
        """Persist stdout for this invocation when it fits the size budget."""
        if not self.enabled or len(output) > self.max_entry_bytes:
            return
        key = self._key(args, file, extra_files)
        path = self._entry_path(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd, tmp_name = tempfile.mkstemp(
                dir=path.parent, prefix=".hledger-cache-", suffix=".tmp"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump({"stdout": output}, handle)
                os.replace(tmp_name, path)
            except BaseException:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise
        except OSError:
            return
        self._maybe_prune()

    def clear(self) -> None:
        """Remove all cache entries (used by tests and explicit resets)."""
        try:
            entries = list(self.directory.glob("*.json"))
        except OSError:
            return
        for entry in entries:
            try:
                entry.unlink()
            except OSError:
                pass

    def _maybe_prune(self) -> None:
        """Occasionally remove the oldest entries beyond ``max_entries``."""
        with self._prune_lock:
            self._puts += 1
            if self._puts % 16 != 0:
                return
        try:
            entries = sorted(
                self.directory.glob("*.json"),
                key=lambda path: path.stat().st_mtime,
            )
        except OSError:
            return
        total_bytes = 0
        sizes: list[tuple[Path, int]] = []
        for entry in entries:
            try:
                size = entry.stat().st_size
            except OSError:
                continue
            sizes.append((entry, size))
            total_bytes += size

        remove_count = max(len(sizes) - self.max_entries, 0)
        removed = 0
        for entry, size in sizes:
            if removed >= remove_count and total_bytes <= self.max_bytes:
                break
            try:
                entry.unlink()
            except OSError:
                continue
            removed += 1
            total_bytes -= size


#: Process-wide persistent cache used by :func:`hledger_textual.hledger.run_hledger`.
disk_cache = HledgerDiskCache()
