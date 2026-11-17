"""Helpers for running independent data loads concurrently."""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

T = TypeVar("T")

# Upper bound for concurrent data loads (and hledger subprocesses).  hledger
# subprocesses are single-threaded, so a few workers give most of the speedup
# without pegging every core or multiplying peak memory use.
MAX_PARALLEL_LOADS = max(2, min(8, os.cpu_count() or 4))


def gather_loads(loaders: Sequence[Callable[[], T]]) -> list[T | Exception]:
    """Run zero-argument loaders concurrently and return results in order.

    Exceptions are returned as values instead of being raised so callers can
    apply their existing per-loader fallbacks.  Loaders should be leaf
    operations; :func:`hledger_textual.hledger.run_hledger` bounds the number
    of hledger subprocesses globally, so nesting this helper is safe.

    Args:
        loaders: Zero-argument callables to execute.

    Returns:
        One entry per loader, either its return value or the exception it
        raised.  Offsets match the input order.
    """
    if not loaders:
        return []
    if len(loaders) == 1:
        try:
            return [loaders[0]()]
        except Exception as exc:  # noqa: BLE001 - returned to the caller
            return [exc]

    with ThreadPoolExecutor(
        max_workers=min(len(loaders), MAX_PARALLEL_LOADS),
        thread_name_prefix="hledger-load",
    ) as executor:
        futures = [executor.submit(loader) for loader in loaders]

    results: list[T | Exception] = []
    for future in futures:
        try:
            results.append(future.result())
        except Exception as exc:  # noqa: BLE001 - returned to the caller
            results.append(exc)
    return results
