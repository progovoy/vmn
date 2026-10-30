"""Summarizing a snapshot under a schema is single-flight: concurrent callers
asking for the same schema wait for the one computation in flight and share
its result, instead of each re-summarizing every row from scratch."""
import threading
import time

import pytest

from vmn_exp.core import index_views
from vmn_exp.core.index_snapshot import IndexSnapshot

SCHEMA = {"loss": {"goal": "min"}}
OTHER = {"loss": {"goal": "max"}}
THREADS = 8


def _snapshot(n=50):
    rows = [{"verstr": f"0.0.{i}", "metrics": {"loss": 1.0}} for i in range(n)]
    parts = {r["verstr"]: ({"loss": {"min": 0.1}}, {}) for r in rows}
    return IndexSnapshot.build("app", 1, rows, {}, metric_parts=parts)


@pytest.fixture
def calls(monkeypatch):
    seen, lock = [], threading.Lock()

    def counting(row, parts, schema):
        with lock:
            seen.append(row["verstr"])
        time.sleep(0.001)  # long enough for the threads to overlap
        return dict(row, metrics={"loss": 0.1})

    monkeypatch.setattr(index_views, "summarized_row", counting)
    return seen


def _together(target, n=THREADS):
    barrier, out, errors = threading.Barrier(n), [None] * n, []

    def run(i):
        barrier.wait()
        try:
            out[i] = target()
        except Exception as exc:  # noqa: BLE001 - collected for the assertion
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not any(t.is_alive() for t in threads), "a caller is wedged"
    return out, errors


def test_concurrent_summarized_computes_each_row_once_and_shares_the_view(calls):
    snap = _snapshot()
    views, errors = _together(lambda: snap.summarized(SCHEMA))
    assert not errors
    assert sorted(calls) == sorted(r["verstr"] for r in snap.rows)
    assert all(v is views[0] for v in views)
    assert snap.summarized(SCHEMA) is views[0]
    assert len(calls) == len(snap.rows)


def test_concurrent_schema_rows_compute_each_row_once(calls):
    snap = _snapshot()
    memo = index_views.SchemaRows()
    _, errors = _together(lambda: memo.rows(snap.rows, snap.metric_parts, SCHEMA))
    assert not errors
    assert sorted(calls) == sorted(r["verstr"] for r in snap.rows)


def test_a_failed_computation_does_not_wedge_waiters(monkeypatch):
    failed, lock = [], threading.Lock()

    def flaky(row, parts, schema):
        time.sleep(0.001)
        with lock:
            if not failed:
                failed.append(row["verstr"])
                raise RuntimeError("boom")
        return dict(row, metrics={"loss": 0.1})

    monkeypatch.setattr(index_views, "summarized_row", flaky)
    snap = _snapshot()
    _, errors = _together(lambda: snap.summarized(SCHEMA))
    assert len(errors) <= 1
    assert snap.summarized(SCHEMA).rows[0]["metrics"] == {"loss": 0.1}


def test_different_schemas_compute_independently(monkeypatch):
    blocked, release = threading.Event(), threading.Event()

    def gated(row, parts, schema):
        if schema == SCHEMA:
            blocked.set()
            assert release.wait(30)
        return dict(row, metrics={"loss": 0.1})

    monkeypatch.setattr(index_views, "summarized_row", gated)
    snap = _snapshot(n=2)
    slow = threading.Thread(target=snap.summarized, args=(SCHEMA,))
    slow.start()
    assert blocked.wait(30)
    try:
        assert snap.summarized(OTHER).rows[0]["metrics"] == {"loss": 0.1}
    finally:
        release.set()
        slow.join(timeout=30)
