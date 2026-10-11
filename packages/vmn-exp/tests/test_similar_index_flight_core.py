"""One build per snapshot (vmn_exp.core.similar_cache): concurrent searches on
a snapshot wait for a single build of its similar index; a builder stopped by
its deadline leaves the build to a waiter. A lineage of snapshots (the UI: one
per workspace app, ``IndexLineages``) builds on a background thread, from its
last index: a caller past its deadline raises while the build goes on."""
import threading
import time

import pytest
from similar_fixtures import FakeSnapshot, changed, run
from vmn_exp.core import similar_index
from vmn_exp.core.similar import SimilarDeadlineExceeded, similar_runs
from vmn_exp.core.similar_cache import IndexLineages
from vmn_exp.core.similar_index import index_for

RUNS = 40
LOSS = changed(files=["src/loss.py"], symbols=["src/loss.py::focal_loss"])


def _snapshot(rows=None, **kw):
    rows = rows or [run(f"r{i}", params={"lr": 0.1}) for i in range(RUNS)]
    return FakeSnapshot(rows, features={row["verstr"]: LOSS for row in rows}, **kw)


@pytest.fixture
def slow_build(monkeypatch):
    """Profiles take 2 ms each (a build ~80 ms); yields the verstrs built."""
    calls, real = [], similar_index.build_profile

    def slow(row=None, *args, **kwargs):
        calls.append(row["verstr"])
        time.sleep(0.002)
        return real(row, *args, **kwargs)

    monkeypatch.setattr(similar_index, "build_profile", slow)
    return calls


def _together(n, work):
    """*work()* on *n* threads started at once: ``(results, errors)``."""
    barrier, results, errors = threading.Barrier(n), [], []

    def one():
        barrier.wait()
        try:
            results.append(work())
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=one) for _ in range(n)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results, errors


def test_concurrent_callers_on_one_snapshot_share_a_single_build(slow_build):
    snapshot = _snapshot()
    results, errors = _together(4, lambda: index_for(snapshot))
    assert errors == []
    assert len(slow_build) == RUNS
    assert all(index is results[0] for index in results)


def test_concurrent_searches_on_one_snapshot_build_its_index_once(slow_build):
    snapshot = _snapshot()
    target = {"row": run("t", params={"lr": 0.1}), "features": LOSS}
    results, errors = _together(4, lambda: similar_runs(snapshot, target, top=3))
    assert errors == [] and len(results) == 4
    assert len(slow_build) == RUNS


def test_a_builder_past_its_deadline_leaves_the_build_to_a_waiter(slow_build):
    snapshot = _snapshot()
    failed = []

    def hurried():
        try:
            index_for(snapshot, deadline=time.monotonic() + 0.02)
        except SimilarDeadlineExceeded:
            failed.append(True)

    first = threading.Thread(target=hurried)
    first.start()
    time.sleep(0.005)
    index = index_for(snapshot)  # waits for the hurried build, then builds
    first.join()
    assert failed == [True]
    assert index.row("r39") is not None and index is index_for(snapshot)


def test_a_lineage_build_outlives_a_caller_past_its_deadline(slow_build):
    lineages, snapshot = IndexLineages(), _snapshot()
    with pytest.raises(SimilarDeadlineExceeded):
        lineages.index_for("app", snapshot, deadline=time.monotonic() + 0.01)
    index = lineages.index_for("app", snapshot, deadline=time.monotonic() + 5)
    assert len(slow_build) == RUNS  # one build, finished in the background
    assert index is index_for(snapshot)


def test_concurrent_lineage_callers_on_a_new_snapshot_build_once(slow_build):
    lineages = IndexLineages()
    first = _snapshot()
    lineages.index_for("app", first, deadline=time.monotonic() + 5)
    rows = list(first.rows) + [run("new", params={"lr": 0.1})]
    later = _snapshot(rows)
    slow_build.clear()
    results, errors = _together(
        4, lambda: lineages.index_for("app", later, deadline=time.monotonic() + 5))
    assert errors == []
    assert slow_build == ["new"]  # built once, from the lineage's last index
    assert all(index is results[0] for index in results)


def test_a_lineage_snapshot_changing_nothing_it_reads_gets_its_last_index(slow_build):
    lineages = IndexLineages()
    rows = [run(f"r{i}", params={"lr": 0.1}) for i in range(RUNS)]
    first = lineages.index_for("app", _snapshot(rows, run_states={"r1": {"heartbeat": 1}}))
    slow_build.clear()
    later = lineages.index_for("app", _snapshot(rows, run_states={"r1": {"heartbeat": 2}}))
    assert later is first and slow_build == []


def test_lineages_are_kept_apart(slow_build):
    lineages = IndexLineages()
    rows = [run(f"r{i}", params={"lr": 0.1}) for i in range(RUNS)]
    lineages.index_for("a", _snapshot(rows))
    slow_build.clear()
    lineages.index_for("b", _snapshot(rows))
    assert len(slow_build) == RUNS


def test_a_failed_lineage_build_raises_in_its_waiters(monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("bad row")

    monkeypatch.setattr(similar_index, "build_profile", broken)
    with pytest.raises(RuntimeError, match="bad row"):
        IndexLineages().index_for("app", _snapshot(), deadline=time.monotonic() + 5)
