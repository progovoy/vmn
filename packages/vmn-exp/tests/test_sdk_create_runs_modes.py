"""``create_runs`` in a git checkout and with a scratch dir in front of the
bucket, and ``create_run(tags=)``."""
import os

import boto3
import pytest
import yaml
from exp_helpers import _bootstrap, _storage
from moto import mock_aws

from vmn_exp.sdk import create_run, create_runs, current_run, start_run
from vmn_exp.sdk.reader import list_runs
from vmn_exp.storage.open import open_storage
from vmn_exp.storage.uri import s3_uri

BUCKET = "ml-exps"
ENV_KEYS = ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_EXPERIMENT_BUCKET",
            "VMN_EXPERIMENT_DIR", "VMN_SNAPSHOT_METADATA", "VMN_WRITER_ID")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _rows(app_name, storage):
    return {r["verstr"]: r for r in list_runs(app_name, storage=storage, use_index=False)}


def test_a_checkout_registers_a_batch_under_its_open_run(app_layout):
    _bootstrap(app_layout)
    app = app_layout.app_name

    with start_run(app, name="outer", system_metrics=False) as outer:
        pods = create_runs(app, [{"name": f"pod{i}", "tags": {"shard": i}} for i in range(3)])
        assert current_run() is outer

    rows = _rows(app, _storage(app_layout))
    assert [rows[v]["name"] for v in pods] == ["pod0", "pod1", "pod2"]
    for i, verstr in enumerate(pods):
        assert (rows[verstr]["parent"], rows[verstr]["status"]) == (outer.id, "created")
        assert rows[verstr]["tags"] == {"shard": str(i)}
        assert rows[verstr]["code_verstr"] == rows[outer.id]["code_verstr"]


def test_create_run_takes_tags_in_its_create_entry(app_layout):
    _bootstrap(app_layout)
    storage = _storage(app_layout)

    verstr = create_run(app_layout.app_name, name="study", tags={"kind": "study"})

    assert _rows(app_layout.app_name, storage)[verstr]["tags"] == {"kind": "study"}
    log = storage.load_merged_log(app_layout.app_name, verstr)
    assert [e["type"] for e in log].count("tags") == 0


@pytest.fixture
def s3(monkeypatch):
    for k, v in dict(AWS_ACCESS_KEY_ID="x", AWS_SECRET_ACCESS_KEY="x",
                     AWS_DEFAULT_REGION="us-east-1").items():
        monkeypatch.setenv(k, v)
    with mock_aws():
        boto3.client("s3").create_bucket(Bucket=BUCKET)
        yield


def _container(tmp_path, monkeypatch):
    image = tmp_path / "image"
    image.mkdir()
    (image / "vmn_metadata.yml").write_text(yaml.safe_dump(
        {"verstr": "1.2.0-dev.abc1234.0000000", "app_name": "trainer",
         "base_version": "1.2.0", "base_commit": "abc1234"}))
    monkeypatch.chdir(image)
    monkeypatch.delenv("VMN_WORKING_DIR", raising=False)
    monkeypatch.setenv("VMN_SNAPSHOT_METADATA", str(image / "vmn_metadata.yml"))
    monkeypatch.setenv("VMN_EXPERIMENT_BUCKET", BUCKET)
    monkeypatch.setenv("VMN_EXPERIMENT_DIR", str(tmp_path / "scratch"))


def test_a_scratch_dir_launcher_ships_the_create_entries_to_the_bucket(tmp_path, monkeypatch, s3):
    _container(tmp_path, monkeypatch)

    trials = create_runs("trainer", [{"name": "t0", "params": {"lr": 0.1},
                                      "tags": {"kind": "trial"}}])

    bucket = open_storage(s3_uri(BUCKET, "vmn"), area="runs")
    row = _rows("trainer", bucket)[trials[0]]
    assert (row["name"], row["params"]["lr"], row["tags"]) == ("t0", 0.1, {"kind": "trial"})
    assert os.path.isdir(tmp_path / "scratch" / "runs" / "trainer")
