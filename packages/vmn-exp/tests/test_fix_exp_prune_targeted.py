"""A targeted prune (``-v <ref>``) reads only its targets: never the experiment
index or a listing of the app's runs, and never trims the change journal."""
from types import SimpleNamespace

import pytest
import yaml

import vmn_exp.core.index as experiment_index
from vmn_exp.cli import prune as prune_mod
from vmn_exp.core.manage import tag_run
from vmn_exp._base import now_iso
from vmn_exp.storage.local import LocalSnapshotStorage
from version_stamp.core.logging import init_stamp_logger

APP = "app"
RUNS = [f"0.0.1-dev.abc1234.r{i}" for i in range(4)]


@pytest.fixture(autouse=True)
def _logger():
    try:
        init_stamp_logger()
    except Exception:
        pass


def _finished():
    return {"state": "finished", "exit_code": 0, "heartbeat": "2026-01-01T00:00:00Z",
            "heartbeat_interval_sec": 30}


def _running():
    return {"state": "running", "heartbeat": now_iso(), "heartbeat_interval_sec": 30,
            "exit_code": None}


def _save(storage, verstr, second, parent=None, state=None):
    meta = {"verstr": verstr, "timestamp": f"2026-01-01T00:00:{second:02d}Z"}
    if parent:
        meta["parent"] = parent
    storage.save(APP, verstr, meta, {})
    storage.save_file(APP, verstr, "run_state.yml", yaml.dump(state or _finished()))
    if parent:
        storage.mark_child(APP, parent, verstr)


@pytest.fixture
def st(tmp_path, monkeypatch):
    """r0 <- r1 (child), r2, r3 independent; no index nor listing may be used."""
    storage = LocalSnapshotStorage(str(tmp_path / "experiments"))
    _save(storage, RUNS[0], 0)
    _save(storage, RUNS[1], 1, parent=RUNS[0])
    _save(storage, RUNS[2], 2)
    _save(storage, RUNS[3], 3)

    def forbidden(*a, **kw):
        raise AssertionError("a targeted prune must not index or list the app")

    monkeypatch.setattr(prune_mod, "indexed_snapshot", forbidden)
    monkeypatch.setattr(experiment_index, "indexed_snapshot", forbidden)
    monkeypatch.setattr(storage, "list_snapshots", forbidden)
    return storage


def _args(*refs, **kw):
    base = dict(version=list(refs), keep=None, older_than=None, force=False,
                dry_run=False, query=None, protect_tag=None)
    return SimpleNamespace(**dict(base, **kw))


def _left(storage):
    return [v for v in RUNS if storage.exists(APP, v)]


def test_targeted_full_verstr_deletes_without_index_or_listing(st, capfd):
    assert prune_mod.experiment_prune(None, {}, st, _args(RUNS[2]), APP) == 0
    assert _left(st) == [RUNS[0], RUNS[1], RUNS[3]]
    assert f"Deleted {RUNS[2]}" in capfd.readouterr().out


def test_targeted_dry_run_without_index_or_listing(st, capfd):
    assert prune_mod.experiment_prune(None, {}, st, _args(RUNS[2], dry_run=True), APP) == 0
    assert _left(st) == RUNS
    assert "Would delete 1 experiments" in capfd.readouterr().out


def test_targeted_unknown_stamped_version_errors(st):
    """A missing dev verstr may be a prefix (that needs a listing); a stamped
    version never is."""
    assert prune_mod.experiment_prune(None, {}, st, _args("9.9.9"), APP) == 1
    assert _left(st) == RUNS


def test_targeted_keeps_a_parent_with_an_untargeted_child(st, capfd):
    assert prune_mod.experiment_prune(None, {}, st, _args(RUNS[0]), APP) == 0
    assert _left(st) == RUNS
    assert "Nothing to prune" in capfd.readouterr().out


def test_targeted_parent_and_child_both_go(st):
    assert prune_mod.experiment_prune(None, {}, st, _args(RUNS[0], RUNS[1]), APP) == 0
    assert _left(st) == [RUNS[2], RUNS[3]]


def test_targeted_parent_of_a_live_targeted_child_is_kept(st, capfd):
    st.save_file(APP, RUNS[1], "run_state.yml", yaml.dump(_running()))
    assert prune_mod.experiment_prune(None, {}, st, _args(RUNS[0], RUNS[1]), APP) == 0
    assert _left(st) == RUNS
    assert "still running" in capfd.readouterr().out


def test_targeted_ignores_a_marker_whose_child_is_gone(st):
    st.delete(APP, RUNS[1])
    assert prune_mod.experiment_prune(None, {}, st, _args(RUNS[0]), APP) == 0
    assert _left(st) == [RUNS[2], RUNS[3]]


def test_targeted_honours_protect_tag_from_the_run_log(st, capfd):
    assert tag_run(st, APP, RUNS[3], {"stage": "prod"})
    args = _args(RUNS[3], protect_tag=["stage"])
    assert prune_mod.experiment_prune(None, {}, st, args, APP) == 0
    assert RUNS[3] in _left(st)
    assert "protected by tag 'stage'" in capfd.readouterr().out


def test_targeted_prune_never_trims_the_journal(st, monkeypatch):
    trims = []
    monkeypatch.setattr(prune_mod, "prune_journal", lambda storage: trims.append(storage))
    assert prune_mod.experiment_prune(None, {}, st, _args(RUNS[2]), APP) == 0
    assert trims == []


def _policy_store(tmp_path):
    storage = LocalSnapshotStorage(str(tmp_path / "policy"))
    for i, verstr in enumerate(RUNS[:2]):
        _save(storage, verstr, i)
    return storage


def test_policy_prune_trims_the_journal(tmp_path, monkeypatch):
    trims = []
    monkeypatch.setattr(prune_mod, "prune_journal", lambda storage: trims.append(storage))
    storage = _policy_store(tmp_path)
    args = SimpleNamespace(keep=0, older_than=None, force=False)
    assert prune_mod.experiment_prune(None, {}, storage, args, APP) == 0
    assert len(trims) == 1


def test_policy_prune_with_no_trim_journal_keeps_the_journal(tmp_path, monkeypatch):
    trims = []
    monkeypatch.setattr(prune_mod, "prune_journal", lambda storage: trims.append(storage))
    storage = _policy_store(tmp_path)
    args = SimpleNamespace(keep=0, older_than=None, force=False, no_trim_journal=True)
    assert prune_mod.experiment_prune(None, {}, storage, args, APP) == 0
    assert trims == []
    assert not storage.exists(APP, RUNS[0])


def test_targeted_prune_checks_code_use_by_a_scoped_listing(st, monkeypatch):
    """Whether a deleted run's code is still used is a listing scoped to its
    code verstr, not of every run of the app."""
    st.update_metadata(APP, RUNS[2], {"code_verstr": "0.0.1-dev.abc1234"})
    scoped = []

    def list_run_verstrs(app_name, code_verstr):
        scoped.append(code_verstr)
        return [v for v in RUNS if st.exists(app_name, v)]

    def forbidden(*a, **kw):
        raise AssertionError("listed every run of the app")

    monkeypatch.setattr(st, "list_run_verstrs", list_run_verstrs, raising=False)
    monkeypatch.setattr(st, "list_record_names", forbidden)
    assert prune_mod.experiment_prune(None, {}, st, _args(RUNS[2]), APP) == 0
    assert scoped == ["0.0.1-dev.abc1234"]
    assert not st.exists(APP, RUNS[2])
