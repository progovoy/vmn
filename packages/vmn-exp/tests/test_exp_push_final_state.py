"""``vmn-exp push`` repairs a remote ``run_state.yml`` that a live run wrote
but never brought to its final state, and only for the same attempt."""
import yaml
from push_helpers import APP, X, local_root, make_run, set_state

from vmn_exp.core.push_run import push_run
from vmn_exp.core.status import RUN_STATE_FILE
from vmn_exp.storage.local import LocalSnapshotStorage


def _remote(tmp_path):
    return LocalSnapshotStorage(str(tmp_path / "remote"), area="runs")


def _live_mirror(local, remote, tmp_path, remote_state):
    """A run written live to both sides: the remote got every beat but not
    the final state, and no push ledger exists."""
    make_run(local, tmp_path)
    remote.save(APP, X, local.load_metadata(APP, X), {})
    remote.save_file(APP, X, RUN_STATE_FILE, yaml.dump(remote_state))
    set_state(local, X, "finished", exit_code=4, attempt="a1")


def _state(storage):
    return yaml.safe_load(storage.load_file(APP, X, RUN_STATE_FILE))


def test_push_replaces_a_running_remote_state_with_the_same_attempts_final_state(tmp_path):
    local, remote = local_root(tmp_path), _remote(tmp_path)
    _live_mirror(local, remote, tmp_path, {"state": "running", "attempt": "a1"})
    outcome = push_run(local, remote, APP, X)
    assert _state(remote) == _state(local)
    assert not any(RUN_STATE_FILE in w for w in outcome.warnings)
    again = push_run(local, remote, APP, X)
    assert not any(RUN_STATE_FILE in w for w in again.warnings)


def test_push_keeps_the_warning_when_another_attempt_finished_the_run(tmp_path):
    local, remote = local_root(tmp_path), _remote(tmp_path)
    theirs = {"state": "finished", "attempt": "b2", "exit_code": 0}
    _live_mirror(local, remote, tmp_path, theirs)
    outcome = push_run(local, remote, APP, X)
    assert _state(remote) == theirs
    assert any(RUN_STATE_FILE in w and "not overwritten" in w for w in outcome.warnings)
