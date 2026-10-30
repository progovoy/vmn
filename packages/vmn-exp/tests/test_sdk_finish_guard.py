"""Two attempts of one run never both end it (client wishlist #1).

Pods of one run (a speculative duplicate, a pod resumed next to a live one)
share its ``run_state.yml``. The first attempt to finish wins: a later
``run.finish`` or ``run.release`` by another attempt leaves the winner's exit
code in place and returns False, and ``manage.finish_run`` refuses a finished
run unless forced. The final write is a compare-and-swap on the state's
version token, so two finishers racing cannot both land.
"""
import pytest
import yaml
from s3_helpers import meta, mocked_bucket, s3_storage

from vmn_exp.core.state_cas import compare_and_save
from vmn_exp.core.status import RUN_STATE_FILE, load_run_state
from vmn_exp.sdk import manage
from vmn_exp.sdk.run import Run
from vmn_exp.snapshot import LocalSnapshotStorage
from vmn_exp.storage.cached import CachedSnapshotStorage

APP = "app"
VERSTR = "0.0.1-dev.aaaaaaa.bbbbbbb"
WHERE = (APP, VERSTR, RUN_STATE_FILE)


@pytest.fixture
def local(tmp_path):
    st = LocalSnapshotStorage(str(tmp_path / "s"), "runs")
    st.save(APP, VERSTR, meta(VERSTR), {})
    return st


@pytest.fixture
def remote(monkeypatch):
    with mocked_bucket(monkeypatch):
        st = s3_storage()
        assert st.create_exclusive(APP, VERSTR, meta(VERSTR), {})
        yield st


@pytest.fixture(params=["local", "remote"])
def storage(request):
    return request.getfixturevalue(request.param)


def _attempts(storage):
    a, b = Run(storage, APP, VERSTR, 60), Run(storage, APP, VERSTR, 60)
    a._open()
    b._open()
    return a, b


def _stored(storage):
    return load_run_state(storage, APP, VERSTR)


def test_a_second_attempts_finish_keeps_the_winners_exit_code(storage):
    a, b = _attempts(storage)

    assert a.finish(0) is True
    assert b.finish(1) is False

    state = _stored(storage)
    assert (state["state"], state["exit_code"]) == ("finished", 0)
    assert state["attempt"] == a._state["attempt"]


def test_a_second_attempts_release_keeps_the_winners_final_state(storage):
    a, b = _attempts(storage)
    a.finish(0)

    assert b.release(reason="evicted") is False

    state = _stored(storage)
    assert (state["state"], state["exit_code"]) == ("finished", 0)
    assert "release_reason" not in state


def test_an_attempt_may_finish_over_another_attempts_release(storage):
    a, b = _attempts(storage)
    assert a.release() is True

    assert b.finish(3) is True
    assert _stored(storage)["exit_code"] == 3


def test_a_finished_run_reports_its_own_win_again(storage):
    a, _ = _attempts(storage)
    assert a.finish(0) is True
    assert a.finish(1) is True
    assert _stored(storage)["exit_code"] == 0


def _racing(side, racer_state):
    """*side*, whose next conditional write first lets *racer_state* land."""
    save = side.save_file_if_match
    raced = []

    def racy(app_name, verstr, filename, data, etag=None):
        if not raced:
            raced.append(True)
            side.save_file(app_name, verstr, filename, yaml.dump(racer_state))
        return save(app_name, verstr, filename, data, etag)

    side.save_file_if_match = racy
    return raced


def _running(storage, attempt):
    storage.save_file(*WHERE, yaml.dump({"state": "running", "attempt": attempt}))


def test_a_stale_token_is_refused(storage):
    _running(storage, "a")
    _, token = storage.load_file_with_token(*WHERE)
    _running(storage, "b")

    assert storage.save_file_if_match(*WHERE, "state: finished\n", token) == (False, None)
    assert _stored(storage)["attempt"] == "b"


def test_a_racing_finisher_loses_cleanly(storage):
    _running(storage, "mine")
    racer = {"state": "finished", "attempt": "racer", "exit_code": 0}
    raced = _racing(storage, racer)

    def finish(stored):
        if stored.get("state") == "finished":
            return None
        return {"state": "finished", "attempt": "mine", "exit_code": 1}

    assert compare_and_save(storage, *WHERE, finish) is None
    assert raced
    assert _stored(storage) == racer


def test_a_racing_heartbeat_is_retried_over(storage):
    _running(storage, "mine")
    _racing(storage, {"state": "running", "attempt": "other"})
    final = {"state": "finished", "attempt": "mine", "exit_code": 0}

    assert compare_and_save(storage, *WHERE, lambda stored: final) == final
    assert _stored(storage) == final


@pytest.fixture
def cached(local):
    return CachedSnapshotStorage(local)


def _finished(storage, exit_code=0, attempt="winner"):
    storage.save_file(*WHERE, yaml.dump(
        {"state": "finished", "attempt": attempt, "exit_code": exit_code}))


def test_manage_finish_refuses_a_finished_run(cached):
    _finished(cached)
    with pytest.raises(manage.FinishRefusedError, match="finished"):
        manage.finish_run(APP, VERSTR, 1, storage=cached)
    assert _stored(cached)["exit_code"] == 0


def test_manage_finish_with_force_overwrites(cached):
    _finished(cached)
    manage.finish_run(APP, VERSTR, 1, force=True, storage=cached)
    assert _stored(cached)["exit_code"] == 1


def test_manage_finish_loses_to_a_racing_finisher(cached, local):
    cached.save_file(*WHERE, yaml.dump({"state": "released", "attempt": "evicted"}))
    _racing(local, {"state": "finished", "attempt": "racer", "exit_code": 0})

    with pytest.raises(manage.FinishRefusedError, match="finished"):
        manage.finish_run(APP, VERSTR, 1, storage=cached)
    assert _stored(cached)["attempt"] == "racer"
