"""The submission hint's budget bounds its work, not only the wait for it:
the search runs on the calling thread under a deadline, so no thread is left
scoring once the budget is spent, and nothing is printed past it."""
import argparse
import threading
import time

import pytest
from exp_helpers import _bootstrap, _exp, _storage
from similar_seed import TRAIN_STEP, features, seed, verstr
from vmn_exp.cli import similar_hint
from vmn_exp.core import similar, similar_index

CHANGES = features(["train.py"], [TRAIN_STEP], author="alice@x.io")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_SWEEP_TRIAL", "VMN_SNAPSHOT_METADATA",
                "VMN_EXPERIMENT_STORE", "VMN_WRITER_ID"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(similar_hint, "BUDGET_SEC", 60.0)


def _warm_app_with_priors(app_layout, count):
    """*count* past runs changing train_step in a warm index cache, and a
    new run changing it too; returns the storage and the new run."""
    _bootstrap(app_layout)
    storage, app = _storage(app_layout), app_layout.app_name
    for n in range(1, count + 1):
        seed(storage, app, verstr(n, commit="0000000"), changes=CHANGES)
    assert _exp(app, action="list") == 0
    return storage, seed(storage, app, verstr(count + 1, commit="0000000"), changes=CHANGES)


def _hint(storage, app_layout, new, capfd):
    capfd.readouterr()
    similar_hint.print_hint(storage, app_layout.app_name, new, argparse.Namespace(), {})
    return [line for line in capfd.readouterr().err.splitlines() if "similar run" in line]


def _hint_threads():
    return [t for t in threading.enumerate() if t.name == "vmn-similar-hint" and t.is_alive()]


def test_the_hint_searches_on_the_calling_thread(app_layout, capfd, monkeypatch):
    storage, new = _warm_app_with_priors(app_layout, 1)
    threads, real = [], similar_hint.search

    def recorded(*args, **kwargs):
        threads.append(threading.current_thread())
        return real(*args, **kwargs)

    monkeypatch.setattr(similar_hint, "search", recorded)
    assert len(_hint(storage, app_layout, new, capfd)) == 1
    assert threads == [threading.current_thread()]


def test_a_hint_over_budget_prints_nothing_and_leaves_no_thread_behind(app_layout, capfd,
                                                                      monkeypatch):
    storage, new = _warm_app_with_priors(app_layout, 1)
    monkeypatch.setattr(similar_hint, "BUDGET_SEC", 0.05)
    real = similar_hint.search

    def slow(*args, **kwargs):
        time.sleep(0.5)
        return real(*args, **kwargs)

    monkeypatch.setattr(similar_hint, "search", slow)
    assert _hint(storage, app_layout, new, capfd) == []
    assert _hint_threads() == []


def test_the_budget_stops_the_scoring_itself(app_layout, capfd, monkeypatch):
    storage, new = _warm_app_with_priors(app_layout, 3)
    now = [0.0]
    monkeypatch.setattr(similar_hint, "_clock", lambda: now[0])
    monkeypatch.setattr(similar_index, "_clock", lambda: now[0])
    monkeypatch.setattr(similar_index, "DEADLINE_CHECK_EVERY", 1)
    monkeypatch.setattr(similar_hint, "BUDGET_SEC", 0.3)
    scored, real = [], similar.score

    def one_second_each(*args, **kwargs):
        scored.append(1)
        now[0] += 1.0
        return real(*args, **kwargs)

    monkeypatch.setattr(similar, "score", one_second_each)
    assert _hint(storage, app_layout, new, capfd) == []
    assert len(scored) == 1
