"""``import-mlflow --refresh-features`` (plan 18 §3.6): an already-imported run
that lacks a ``features`` entry at the current version gets one built from the
MLflow tags (its branch inside, since the metadata keeps what it has), and its
MLflow note when the record has none. Nothing else is rewritten, and a second
refresh changes nothing.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from backfill_helpers import host_logs
from mlflow_fixtures import MlflowFixtureBuilder
from vmn_exp.core.writer import claim_record
from vmn_exp.importers.import_records import IMPORT_WRITER, import_run, run_verstr
from vmn_exp.importers.mlflow_filestore import iter_runs
from vmn_exp.storage.local import LocalSnapshotStorage

APP = "myapp"
RUN_ID = "a" * 32
NOTE = "try gamma=2"
TAGS = {
    "mlflow.user": "alice",
    "mlflow.note.content": NOTE,
    "mlflow.source.git.branch": "feat/focal",
    "mlflow.source.name": "train.py",
}


@pytest.fixture(autouse=True)
def _refresher(monkeypatch):
    monkeypatch.setenv("VMN_WRITER_ID", "refresher")


def _run(tmp_path, tags=TAGS, run_id=RUN_ID):
    mlruns = tmp_path / "mlruns"
    builder = MlflowFixtureBuilder(mlruns)
    builder.add_experiment("1", "exp_one")
    builder.add_run("1", run_id, tags=tags)
    return next(iter_runs(mlruns))


def _storage(tmp_path):
    return LocalSnapshotStorage(str(tmp_path / "store"), area="runs")


def _legacy_record(storage, run, note=None, run_id=None):
    """A record imported before features existed: metadata without the mapped
    tags and a create entry, no features entry."""
    verstr = run_verstr(run["run_id"])
    meta = {"verstr": verstr, "code_verstr": verstr,
            "imported_from": {"tool": "mlflow", "run_id": run_id or run["run_id"],
                              "experiment_id": "1", "experiment_name": "exp_one",
                              "source_commit": None, "artifact_uri": run["artifact_uri"]}}
    if note:
        meta["note"] = note
    assert claim_record(storage, APP, verstr, meta)
    storage.append_log_entries(APP, verstr, IMPORT_WRITER, [
        {"timestamp": "2023-11-14T22:13:20.000000Z", "type": "create"}])
    return verstr


def _features(storage, verstr, writer=None):
    if writer:
        entries = host_logs(storage, APP, verstr).get(writer) or []
    else:
        entries = storage.load_merged_log(APP, verstr)
    return [e for e in entries if e.get("type") == "features"]


def test_refresh_appends_the_features_a_legacy_import_lacks(tmp_path):
    storage, run = _storage(tmp_path), _run(tmp_path)
    verstr = _legacy_record(storage, run)

    assert import_run(storage, APP, run, refresh_features=True) == "refreshed"

    [entry] = _features(storage, verstr, writer="refresher")
    assert entry["source"] == "mlflow"
    assert entry["author"] == {"os_user": "alice", "source": "mlflow"}
    assert entry["entrypoint"] == "train.py"
    assert entry["branch"] == "feat/focal"
    assert [e["type"] for e in host_logs(storage, APP, verstr)[IMPORT_WRITER]] \
        == ["create"]


def test_refresh_sets_the_mlflow_note_on_a_record_without_one(tmp_path):
    storage, run = _storage(tmp_path), _run(tmp_path)
    verstr = _legacy_record(storage, run)

    import_run(storage, APP, run, refresh_features=True)

    assert storage.load_metadata(APP, verstr)["note"] == NOTE


def test_refresh_keeps_a_note_the_record_already_has(tmp_path):
    storage, run = _storage(tmp_path), _run(tmp_path)
    verstr = _legacy_record(storage, run, note="mine")

    assert import_run(storage, APP, run, refresh_features=True) == "refreshed"

    assert storage.load_metadata(APP, verstr)["note"] == "mine"


def test_a_second_refresh_changes_nothing(tmp_path):
    storage, run = _storage(tmp_path), _run(tmp_path)
    verstr = _legacy_record(storage, run)
    import_run(storage, APP, run, refresh_features=True)

    assert import_run(storage, APP, run, refresh_features=True) == "skipped"

    assert len(_features(storage, verstr)) == 1


def test_refresh_skips_a_new_import_that_already_has_its_features(tmp_path):
    storage, run = _storage(tmp_path), _run(tmp_path)
    assert import_run(storage, APP, run) == "created"

    assert import_run(storage, APP, run, refresh_features=True) == "skipped"

    assert len(_features(storage, run_verstr(RUN_ID))) == 1


def test_refresh_picks_up_a_note_added_in_mlflow_after_the_import(tmp_path):
    storage = _storage(tmp_path)
    plain = {k: v for k, v in TAGS.items() if k != "mlflow.note.content"}
    assert import_run(storage, APP, _run(tmp_path, plain)) == "created"
    run = _run(tmp_path)  # the note was written in MLflow since

    assert import_run(storage, APP, run, refresh_features=True) == "refreshed"

    verstr = run_verstr(RUN_ID)
    assert storage.load_metadata(APP, verstr)["note"] == NOTE
    assert len(_features(storage, verstr)) == 1


def test_without_refresh_features_a_legacy_import_stays_untouched(tmp_path):
    storage, run = _storage(tmp_path), _run(tmp_path)
    verstr = _legacy_record(storage, run)

    assert import_run(storage, APP, run) == "skipped"

    assert _features(storage, verstr) == []
    assert "note" not in storage.load_metadata(APP, verstr)


def test_refresh_never_touches_another_runs_record(tmp_path):
    storage, run = _storage(tmp_path), _run(tmp_path)
    verstr = _legacy_record(storage, run, run_id="a" * 12 + "b" * 20)

    assert import_run(storage, APP, run, refresh_features=True) == "skipped"

    assert _features(storage, verstr) == []
    assert "note" not in storage.load_metadata(APP, verstr)


def test_refreshed_rows_show_the_mlflow_author_and_note(tmp_path):
    from vmn_exp.sdk.reader import list_runs

    storage, run = _storage(tmp_path), _run(tmp_path)
    _legacy_record(storage, run)
    [before] = list_runs(APP, storage=storage)
    assert before["author"] is None

    import_run(storage, APP, run, refresh_features=True)

    for use_index in (True, False):
        [row] = list_runs(APP, storage=storage, use_index=use_index)
        assert (row["author"], row["note"]) == ("alice", NOTE)


def test_a_refreshed_run_has_the_mlflow_branch_in_its_features(tmp_path):
    from vmn_exp.core.index import direct_snapshot

    storage, run = _storage(tmp_path), _run(tmp_path)
    verstr = _legacy_record(storage, run)
    import_run(storage, APP, run, refresh_features=True)

    snap = direct_snapshot(storage, APP)
    assert snap.features_of(verstr)["branch"] == "feat/focal"
