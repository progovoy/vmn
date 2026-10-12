"""``vmn-exp import-mlflow --refresh-features [--repo PATH]`` end to end: the
flags parse, the summary counts refreshed runs (only when the flag is given),
``--repo`` fills the commit's changes, and a refresh writes through the
remote store like any one-shot append.
"""
from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

sys.path.insert(0, str(Path(__file__).parent))

from backfill_helpers import host_logs
from mlflow_fixtures import MlflowFixtureBuilder
from version_stamp.cli.args import parse_user_commands
from vmn_exp.importers.import_records import IMPORT_WRITER, run_verstr
from vmn_exp.storage.local import LocalSnapshotStorage

APP = "myapp"
RUN_A = "a" * 32
RUN_B = "b" * 32
BUCKET = "refresh-bkt"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    for key in ("VMN_EXPERIMENT_STORE", "VMN_EXPERIMENT_BUCKET", "VMN_EXPERIMENT_PREFIX",
                "VMN_EXPERIMENT_ENDPOINT_URL", "VMN_EXPERIMENT_DIR", "VMN_WORKING_DIR"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("VMN_WRITER_ID", "refresher")
    monkeypatch.chdir(tmp_path)


def _args(mlruns, **overrides):
    values = dict(command="exp", action="import-mlflow", name=APP, mlruns=str(mlruns),
                  tracking_uri=None, experiment=[], skip_artifacts=False,
                  include_deleted=False, dry_run=False, workers=4, store=None,
                  bucket=None, prefix=None, endpoint_url=None, experiment_dir=None)
    values.update(overrides)
    return types.SimpleNamespace(**values)


def _call(args):
    from vmn_exp.importers.cli import import_mlflow_run_without_repo
    return import_mlflow_run_without_repo(args)


def _mlruns(tmp_path, tags_a=None, tags_b=None):
    mlruns = tmp_path / "mlruns"
    builder = MlflowFixtureBuilder(mlruns)
    builder.add_experiment("1", "exp_one")
    builder.add_run("1", RUN_A, tags=tags_a or {})
    builder.add_run("1", RUN_B, tags=tags_b or {})
    return mlruns


def _summary(capsys):
    return capsys.readouterr().out.strip().splitlines()[-1]


def _features(storage, run_id):
    return [e for e in storage.load_merged_log(APP, run_verstr(run_id))
            if e.get("type") == "features"]


def test_the_refresh_flags_parse():
    args = parse_user_commands(["exp", "import-mlflow", APP, "--mlruns", "/x",
                                "--refresh-features", "--repo", "/r"])
    assert (args.refresh_features, args.repo) == (True, "/r")

    plain = parse_user_commands(["exp", "import-mlflow", APP, "--mlruns", "/x"])
    assert (plain.refresh_features, plain.repo) == (False, None)


def test_without_the_flag_the_summary_line_is_unchanged(tmp_path, capsys):
    rc = _call(_args(_mlruns(tmp_path), experiment_dir=str(tmp_path / "data")))

    assert rc == 0
    assert _summary(capsys) == "imported 2, skipped 0 (already present), resumed 0, failed 0"


def test_the_summary_counts_refreshed_runs(tmp_path, capsys):
    data = str(tmp_path / "data")
    assert _call(_args(_mlruns(tmp_path), experiment_dir=data)) == 0
    _mlruns(tmp_path, tags_a={"mlflow.note.content": "added later"})

    rc = _call(_args(tmp_path / "mlruns", experiment_dir=data, refresh_features=True))

    assert rc == 0
    assert _summary(capsys) == ("imported 0, skipped 1 (already present), resumed 0, "
                                "refreshed 1, failed 0")
    storage = LocalSnapshotStorage(data, area="runs")
    assert storage.load_metadata(APP, run_verstr(RUN_A))["note"] == "added later"


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), check=True,
                          capture_output=True, text=True).stdout.strip()


def _checkout(tmp_path):
    """A checkout whose feat branch changed train.py; returns (path, tip)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (("init", "-q"), ("checkout", "-q", "-b", "main"),
                 ("config", "user.email", "t@acme.io"), ("config", "user.name", "T")):
        _git(repo, *args)
    (repo / "train.py").write_text("def train():\n    return 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "feat")
    (repo / "train.py").write_text("def train():\n    return 2\n")
    _git(repo, "commit", "-q", "-am", "tweak")
    return repo, _git(repo, "rev-parse", "HEAD")


def test_repo_fills_the_changes_of_each_runs_source_commit(tmp_path):
    repo, tip = _checkout(tmp_path)
    data = str(tmp_path / "data")
    mlruns = _mlruns(tmp_path, tags_a={"mlflow.source.git.commit": tip},
                     tags_b={"mlflow.source.git.commit": "0" * 40})

    assert _call(_args(mlruns, experiment_dir=data, repo=str(repo))) == 0

    storage = LocalSnapshotStorage(data, area="runs")
    [with_commit] = _features(storage, RUN_A)
    assert with_commit["changed"]["files"] == ["train.py"]
    assert with_commit["changed_source"] == "commit"
    [unknown_commit] = _features(storage, RUN_B)
    assert "changed" not in unknown_commit


@pytest.fixture
def s3(monkeypatch):
    for key, value in dict(AWS_ACCESS_KEY_ID="x", AWS_SECRET_ACCESS_KEY="x",
                           AWS_DEFAULT_REGION="us-east-1").items():
        monkeypatch.setenv(key, value)
    with mock_aws():
        boto3.client("s3").create_bucket(Bucket=BUCKET)
        yield f"s3://{BUCKET}/vmn"


def _legacy_import(store, root, mlruns):
    """Records imported before features existed, synced to *store*."""
    from vmn_exp.core.storage_resolve import resolve_experiment_storage
    from vmn_exp.core.writer import claim_record, sync_to_remote
    from vmn_exp.importers.mlflow_filestore import iter_runs

    storage = resolve_experiment_storage(store=store, dir=root, repo_root=False)
    for run in iter_runs(mlruns):
        verstr = run_verstr(run["run_id"])
        claim_record(storage, APP, verstr, {
            "verstr": verstr, "code_verstr": verstr,
            "imported_from": {"tool": "mlflow", "run_id": run["run_id"]}})
        storage.append_log_entries(APP, verstr, IMPORT_WRITER, [
            {"timestamp": "2023-11-14T22:13:20.000000Z", "type": "create"}])
        sync_to_remote(storage, APP, verstr, IMPORT_WRITER)


@pytest.mark.parametrize("fresh_root", [False, True], ids=["store-only", "fresh-root"])
def test_a_refresh_writes_through_the_remote_store(tmp_path, s3, capsys, fresh_root):
    from vmn_exp.core.storage_resolve import resolve_experiment_storage

    mlruns = _mlruns(tmp_path, tags_a={"mlflow.user": "alice", "mlflow.note.content": "n"})
    _legacy_import(s3, str(tmp_path / "host-a"), mlruns)
    root = str(tmp_path / "host-b") if fresh_root else None

    rc = _call(_args(mlruns, store=s3, experiment_dir=root, refresh_features=True))

    assert rc == 0
    assert "refreshed 2" in _summary(capsys)
    remote = resolve_experiment_storage(store=s3, repo_root=False)
    by_writer = host_logs(remote, APP, run_verstr(RUN_A))
    assert [e["type"] for e in by_writer[IMPORT_WRITER]] == ["create"]
    [entry] = [e for e in by_writer["refresher"] if e["type"] == "features"]
    assert entry["author"] == {"os_user": "alice", "source": "mlflow"}
    assert remote.load_metadata(APP, run_verstr(RUN_A))["note"] == "n"


def test_a_repo_that_is_no_directory_is_refused_before_anything_is_written(tmp_path, capsys):
    data = tmp_path / "data"

    rc = _call(_args(_mlruns(tmp_path), experiment_dir=str(data),
                     repo=str(tmp_path / "nowhere")))

    assert rc == 1
    assert "--repo" in capsys.readouterr().out
    assert not data.exists()
