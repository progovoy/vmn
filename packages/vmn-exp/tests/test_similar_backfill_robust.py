"""``vmn-exp similar-backfill`` on a store that misbehaves or holds old runs:

* a code object the store lists but could not read (a transient failure)
  fails the run and writes nothing, so the next backfill retries it —
  ``partial`` is only for code the store no longer has;
* a run whose create entry the v1 migration wrote (pseudo-writer ``v1``)
  names its run state's host as the writer, or none;
* a malformed run state fails that run only;
* an older entry's ``changed``/``commits`` survive when the code is gone.
"""
import pytest
from backfill_helpers import (
    CODE,
    CREATOR,
    FILES,
    KEY,
    as_backfiller,
    dirty_run,
    features_entries,
    seed_code,
    seed_run,
)
from exp_helpers import _bootstrap, _exp, _storage
from vmn_exp.cli import similar_backfill
from vmn_exp.core.code_store import code_storage
from vmn_exp.core.features import FEATURES_VERSION
from vmn_exp.core.status import RUN_STATE_FILE

V1 = CODE
V2 = CODE + ".r2"


@pytest.fixture
def store(app_layout, monkeypatch):
    _bootstrap(app_layout)
    as_backfiller(monkeypatch)
    return _storage(app_layout)


def _cli_backfill(app_layout, capfd):
    capfd.readouterr()
    code = _exp(app_layout.app_name, action="similar-backfill")
    return code, capfd.readouterr().out.splitlines()


def _backfill(store, app):
    return {verstr: (status, detail)
            for verstr, status, detail in similar_backfill.backfill_app(store, app)}


def _flaky_code_reads(store, failing, monkeypatch, fail=lambda name: None):
    """Reads of the code area's *failing* file names go wrong until undone."""
    area = code_storage(store)
    real = area.load_file

    def load_file(app_name, verstr, filename):
        return fail(filename) if filename in failing else real(app_name, verstr, filename)

    monkeypatch.setattr(area, "load_file", load_file)


@pytest.mark.parametrize("failing", ["metadata.yml", "working_tree.patch"])
def test_a_code_object_that_could_not_be_read_fails_and_is_retried(
    app_layout, store, monkeypatch, failing,
):
    app = app_layout.app_name
    seed_code(store, app)
    dirty_run(store, app, V1)
    with monkeypatch.context() as patched:
        _flaky_code_reads(store, {failing}, patched)
        status, detail = _backfill(store, app)[V1]

    assert status == "failed" and "could not read" in detail
    assert features_entries(store, app, V1) == []
    assert _backfill(store, app)[V1][0] == "backfilled"
    assert sorted(features_entries(store, app, V1)[0]["changed"]["files"]) == FILES


def test_a_code_read_that_raises_fails_the_run(app_layout, store, monkeypatch):
    app = app_layout.app_name
    seed_code(store, app)
    dirty_run(store, app, V1)

    def boom(name):
        raise OSError("bucket on fire")

    _flaky_code_reads(store, {"metadata.yml"}, monkeypatch, boom)

    assert _backfill(store, app)[V1] == ("failed", "bucket on fire")
    assert features_entries(store, app, V1) == []


def test_a_snapshot_runs_unreadable_code_object_fails_rather_than_partial(
    app_layout, store, monkeypatch,
):
    app = app_layout.app_name
    seed_code(store, app)
    seed_run(store, app, V1, from_snapshot=True, dirty_states=["pending"])
    _flaky_code_reads(store, {"metadata.yml"}, monkeypatch)

    status, detail = _backfill(store, app)[V1]

    assert status == "failed" and KEY in detail
    assert features_entries(store, app, V1) == []


def _legacy_run(store, app, verstr, host=None):
    """A run ``vmn-exp migrate`` converted: its create entry is writer ``v1``'s."""
    store.save(app, verstr, {"verstr": verstr, "timestamp": "2026-01-01T00:00:00Z",
                             "base_version": "0.0.2", "base_commit": "abc1234",
                             "code_verstr": CODE, "dirty_states": []}, {})
    store.append_log_entry(app, verstr, "v1", {"timestamp": "2026-01-01T00:00:01Z",
                                               "type": "create", "note": None})
    if host is not None:
        store.save_file(app, verstr, RUN_STATE_FILE,
                        f"state: finished\nexit_code: 0\nhost: {host}\n")


def test_a_migrated_runs_writer_is_its_run_states_host(app_layout, store):
    app = app_layout.app_name
    _legacy_run(store, app, V1, host="gpu-03")

    assert _backfill(store, app)[V1][0] == "backfilled"
    assert features_entries(store, app, V1)[0]["author"] == {"writer": "gpu-03"}


def test_a_migrated_run_without_a_host_names_no_writer(app_layout, store):
    app = app_layout.app_name
    _legacy_run(store, app, V1)

    assert _backfill(store, app)[V1][0] == "backfilled"
    assert "author" not in features_entries(store, app, V1)[0]


def test_a_malformed_run_state_fails_that_run_only(app_layout, store, capfd):
    app = app_layout.app_name
    seed_run(store, app, V1, state=None)
    store.save_file(app, V1, RUN_STATE_FILE, "state: finished\nexit_code: oops\n")
    seed_run(store, app, V2)

    code, lines = _cli_backfill(app_layout, capfd)

    assert code == 1
    assert any(line.startswith(f"{V1}  failed (") for line in lines), lines
    assert f"{V2}  backfilled (clean tree)" in lines
    assert lines[-1] == "backfilled 1, partial 0, skipped 0, failed 1"


def test_an_older_entrys_changes_survive_when_the_code_is_gone(app_layout, store, capfd):
    app = app_layout.app_name
    author = {"git_user_email": "bob@x.io", "writer": "laptop", "source": "git"}
    older = {"timestamp": "2026-01-01T00:00:02Z", "type": "features",
             "features_version": FEATURES_VERSION - 1, "source": "capture",
             "author": author, "commits": ["old subject"], "truncated": True,
             "changed": {"files": ["old.py"], "symbols": ["old.py::f"],
                         "untracked": ["notes/idea.md"]}}
    dirty_run(store, app, V1, log=[older])

    code, lines = _cli_backfill(app_layout, capfd)

    assert code == 0
    assert f"{V1}  partial (code object {KEY} is missing)" in lines
    entry = features_entries(store, app, V1)[-1]
    assert entry["features_version"] == FEATURES_VERSION and entry["source"] == "backfill"
    assert entry["author"] == author
    assert entry["changed"] == older["changed"]
    assert entry["commits"] == ["old subject"] and entry["truncated"] is True
    assert CREATOR not in str(entry)
