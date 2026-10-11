"""``run.set_intent`` on a finished run reaches the remote: nothing ships the
log after ``finish()``, so the call appends and syncs at once, like
``vmn-exp add``; a remote that fails it never raises into the caller."""
import pytest
from vmn_exp.core.fold import fold_intent, fold_log
from vmn_exp.sdk.run import Run
from vmn_exp.snapshot import LocalSnapshotStorage
from vmn_exp.storage.cached import CachedSnapshotStorage

APP = "app"
VERSTR = "0.0.1-dev.aaaaaaa.bbbbbbb"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_SNAPSHOT_METADATA"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def remote(tmp_path):
    return LocalSnapshotStorage(str(tmp_path / "remote"), "runs")


@pytest.fixture
def finished(tmp_path, remote):
    storage = CachedSnapshotStorage(LocalSnapshotStorage(str(tmp_path / "local"), "runs"),
                                    remote)
    storage.save(APP, VERSTR, {"verstr": VERSTR, "timestamp": "2026-01-01T00:00:00Z"}, {})
    run = Run(storage, APP, VERSTR, 60)
    run._open()
    run.finish()
    return run


def _remote_intent(remote):
    return fold_intent(fold_log(remote.load_merged_log(APP, VERSTR)))


def test_an_intent_set_after_finish_reaches_the_remote(finished, remote):
    finished.set_intent("why this ran", keywords=["gamma"])

    assert _remote_intent(remote)["text"] == "why this ran"


def test_the_latest_intent_after_finish_wins_on_the_remote(finished, remote):
    finished.set_intent("first")
    finished.set_intent("second")

    assert _remote_intent(remote)["text"] == "second"


def test_a_failing_sync_after_finish_does_not_raise(finished, monkeypatch):
    def broken(*args):
        raise OSError("remote down")

    monkeypatch.setattr(finished._storage, "sync_log_to_remote", broken)
    finished.set_intent("kept locally")

    log = finished._storage.load_merged_log(APP, VERSTR)
    assert fold_intent(fold_log(log))["text"] == "kept locally"
