"""import-mlflow maps MLflow's own tags (plan 18 §3.6).

A new import keeps the note, branch, source name and repo URL in the record's
metadata, and writes one ``features`` entry (``source: mlflow``) with the
MLflow user as author and the entrypoint. ``mlflow.*`` tags still never become
vmn tags.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from mlflow_fixtures import MlflowFixtureBuilder
from vmn_exp.core.features import FEATURES_VERSION
from vmn_exp.core.writer import claim_record
from vmn_exp.importers.import_records import IMPORT_WRITER, import_run, run_verstr
from vmn_exp.importers.mlflow_filestore import iter_runs
from vmn_exp.storage.local import LocalSnapshotStorage

APP = "myapp"
RUN_ID = "a" * 32
NOTE = "## Focal loss\n\ntry gamma=2 on the long tail"
TAGS = {
    "mlflow.user": "alice",
    "mlflow.note.content": NOTE,
    "mlflow.source.git.branch": "feat/focal",
    "mlflow.source.name": "train.py",
    "mlflow.source.git.repoURL": "git@github.com:acme/models.git",
    "mlflow.source.type": "LOCAL",
    "team": "vision",
}


def _run(tmp_path, tags):
    mlruns = tmp_path / "mlruns"
    builder = MlflowFixtureBuilder(mlruns)
    builder.add_experiment("1", "exp_one")
    builder.add_run("1", RUN_ID, tags=tags)
    return next(iter_runs(mlruns))


def _storage(tmp_path):
    return LocalSnapshotStorage(str(tmp_path / "store"), area="runs")


def _import(tmp_path, tags=TAGS):
    storage = _storage(tmp_path)
    assert import_run(storage, APP, _run(tmp_path, tags)) == "created"
    return storage, run_verstr(RUN_ID)


def _features(storage, verstr):
    return [e for e in storage.load_merged_log(APP, verstr) if e.get("type") == "features"]


def test_a_new_import_keeps_the_mlflow_note_and_branch_in_its_metadata(tmp_path):
    storage, verstr = _import(tmp_path)

    meta = storage.load_metadata(APP, verstr)
    assert meta["note"] == NOTE
    assert meta["branch"] == "feat/focal"


def test_a_new_import_records_the_runs_source_and_repo_url(tmp_path):
    storage, verstr = _import(tmp_path)

    imported = storage.load_metadata(APP, verstr)["imported_from"]
    assert imported["source_name"] == "train.py"
    assert imported["repo_url"] == "git@github.com:acme/models.git"
    assert imported["run_id"] == RUN_ID


def test_a_new_import_writes_one_mlflow_features_entry(tmp_path):
    storage, verstr = _import(tmp_path)

    [entry] = _features(storage, verstr)
    assert entry["features_version"] == FEATURES_VERSION
    assert entry["source"] == "mlflow"
    assert entry["author"] == {"os_user": "alice", "source": "mlflow"}
    assert entry["entrypoint"] == "train.py"
    assert "branch" not in entry  # the metadata holds it
    assert "changed" not in entry  # no checkout to diff in


def test_the_features_entry_is_written_by_the_import_writer(tmp_path):
    storage, verstr = _import(tmp_path)

    by_writer = storage.load_logs_by_writer(APP, verstr)
    assert [w for w, entries in by_writer.items() if entries] == [IMPORT_WRITER]
    assert any(e["type"] == "features" for e in by_writer[IMPORT_WRITER])


def test_an_email_mlflow_user_is_the_authors_git_email(tmp_path):
    storage, verstr = _import(tmp_path, dict(TAGS, **{"mlflow.user": " bob@acme.io \n"}))

    [entry] = _features(storage, verstr)
    assert entry["author"] == {"git_user_email": "bob@acme.io", "source": "mlflow"}


def test_a_project_entry_point_beats_the_source_name(tmp_path):
    tags = dict(TAGS, **{"mlflow.project.entryPoint": "main",
                         "mlflow.source.name": "https://github.com/acme/models"})
    storage, verstr = _import(tmp_path, tags)

    [entry] = _features(storage, verstr)
    assert entry["entrypoint"] == "main"
    imported = storage.load_metadata(APP, verstr)["imported_from"]
    assert imported["source_name"] == "https://github.com/acme/models"


def test_mlflow_tags_still_never_become_vmn_tags(tmp_path):
    storage, verstr = _import(tmp_path)

    tags = {}
    for entry in storage.load_merged_log(APP, verstr):
        if entry.get("type") == "tags":
            tags.update(entry.get("set", {}))
    assert tags == {"team": "vision"}


def test_a_run_without_mlflow_tags_gets_a_bare_features_entry(tmp_path):
    storage, verstr = _import(tmp_path, tags={"team": "vision"})

    [entry] = _features(storage, verstr)
    assert {k: v for k, v in entry.items() if k not in ("timestamp", "_writer")} == {
        "type": "features", "features_version": FEATURES_VERSION, "source": "mlflow"}
    meta = storage.load_metadata(APP, verstr)
    assert "note" not in meta and "branch" not in meta
    assert "source_name" not in meta["imported_from"]
    assert "repo_url" not in meta["imported_from"]


def test_blank_mlflow_tags_are_left_out(tmp_path):
    blank = {key: "  " for key in TAGS if key.startswith("mlflow.")}
    storage, verstr = _import(tmp_path, blank)

    [entry] = _features(storage, verstr)
    assert "author" not in entry and "entrypoint" not in entry
    assert "note" not in storage.load_metadata(APP, verstr)


def test_imported_rows_carry_the_mlflow_author_note_and_branch(tmp_path):
    from vmn_exp.sdk.reader import list_runs

    storage, _ = _import(tmp_path)

    [row] = list_runs(APP, storage=storage, use_index=False)
    assert row["author"] == "alice"
    assert row["note"] == NOTE
    assert row["branch"] == "feat/focal"


def test_a_resumed_import_writes_the_features_entry_too(tmp_path):
    storage = _storage(tmp_path)
    run = _run(tmp_path, TAGS)
    verstr = run_verstr(RUN_ID)
    claim_record(storage, APP, verstr, {
        "verstr": verstr, "code_verstr": verstr,
        "imported_from": {"tool": "mlflow", "run_id": RUN_ID},
    })

    assert import_run(storage, APP, run) == "resumed"
    [entry] = _features(storage, verstr)
    assert entry["author"] == {"os_user": "alice", "source": "mlflow"}
