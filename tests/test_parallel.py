"""Tests for the concurrent loader helper (issue #162)."""

from __future__ import annotations

import threading
import time

from hledger_textual.parallel import gather_loads


def test_empty_returns_empty():
    """No loaders produce no results."""
    assert gather_loads([]) == []


def test_single_loader_runs_inline():
    """A single loader runs without a worker pool."""
    assert gather_loads([lambda: 42]) == [42]


def test_results_preserve_order():
    """Results are returned in input order even when completion order differs."""
    import random

    def _delayed(value: int):
        def _load():
            time.sleep(random.uniform(0, 0.01))
            return value

        return _load

    loaders = [_delayed(i) for i in range(12)]
    assert gather_loads(loaders) == list(range(12))


def test_exceptions_are_returned_not_raised():
    """A failing loader yields its exception while others still run."""

    def _boom():
        raise ValueError("boom")

    results = gather_loads([lambda: 1, _boom, lambda: 3])
    assert results[0] == 1
    assert isinstance(results[1], ValueError)
    assert results[2] == 3


def test_loaders_run_concurrently():
    """Two sleeping loaders overlap rather than running one after another."""
    barrier = threading.Barrier(2)

    def _wait():
        barrier.wait(timeout=2)
        return True

    started = time.perf_counter()
    results = gather_loads([_wait, _wait])
    elapsed = time.perf_counter() - started
    assert results == [True, True]
    assert elapsed < 1.0


def test_exception_string_is_preserved():
    """The original exception object is returned to the caller."""

    error = RuntimeError("keep me")

    def _raise():
        raise error

    result = gather_loads([_raise])[0]
    assert result is error
