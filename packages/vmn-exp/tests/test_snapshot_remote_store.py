"""`vmn snapshot --store <uri>` (and a configured experiment store): vmn-exp
registers the opener, records land in the store's ``snapshots`` area and code
objects in its ``code`` area, shared with experiment runs."""
import json
import os
import shutil

import pytest
import yaml

from vmn_exp.storage.areas import local_store_root
from exp_helpers import _bootstrap, _experiment, _snapshot, extract_dev_verstr


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_STORE", "VMN_EXPERIMENT_BUCKET", "VMN_EXPERIMENT_PREFIX",
                "VMN_EXPERIMENT_ENDPOINT_URL", "VMN_EXPERIMENT_DIR", "VMN_EXP_OFFLINE"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def store_dir(tmp_path):
    return str(tmp_path / "store")


def _uri(store_dir):
    return f"file://{store_dir}"


def _dirty(app_layout, content="dirty"):
    path = os.path.join(app_layout.repo_path, "work.txt")
    if not os.path.exists(path):
        app_layout.write_file_commit_and_push("test_repo_0", "work.txt", "initial")
    with open(path, "w") as f:
        f.write(content)


def _create(app_layout, capfd, **kwargs):
    capfd.readouterr()
    assert _snapshot(app_layout.app_name, **kwargs) == 0
    return extract_dev_verstr(capfd.readouterr().out)


def _records_dir(root, app_layout):
    return os.path.join(root, "snapshots", app_layout.app_name)


def _code_dir(root, app_layout):
    return os.path.join(root, "code", app_layout.app_name)


def _entries(path):
    return sorted(e for e in os.listdir(path) if not e.startswith(".")) if os.path.isdir(path) else []


def _meta(root, app_layout, verstr):
    with open(os.path.join(_records_dir(root, app_layout), verstr, "metadata.yml")) as f:
        return yaml.safe_load(f)


def _configure_store(app_layout, uri):
    conf_path = os.path.join(app_layout.repo_path, ".vmn", app_layout.app_name, "conf.yml")
    app_layout.write_conf(
        conf_path, template="[{major}][.{minor}][.{patch}]",
        experiment={"storage": {"uri": uri}},
    )


def test_create_with_store_writes_records_and_code_to_the_store(app_layout, capfd, store_dir):
    _bootstrap(app_layout)
    _dirty(app_layout)
    verstr = _create(app_layout, capfd, store=_uri(store_dir))

    assert _entries(_records_dir(store_dir, app_layout)) == [verstr]
    meta = _meta(store_dir, app_layout, verstr)
    assert _entries(_code_dir(store_dir, app_layout)) == [meta["code"]]
    assert not os.path.isdir(_records_dir(local_store_root(app_layout.repo_path), app_layout))
    assert _entries(_code_dir(local_store_root(app_layout.repo_path), app_layout)) == []


def test_list_show_note_delete_through_the_store(app_layout, capfd, store_dir):
    _bootstrap(app_layout)
    _dirty(app_layout)
    uri = _uri(store_dir)
    verstr = _create(app_layout, capfd, store=uri, note="first")

    capfd.readouterr()
    assert _snapshot(app_layout.app_name, action="list", store=uri, as_json=True) == 0
    rows = json.loads(capfd.readouterr().out)
    assert [(r["verstr"], r["note"]) for r in rows] == [(verstr, "first")]

    assert _snapshot(app_layout.app_name, action="note", version=verstr,
                     note="renamed", store=uri) == 0
    assert _meta(store_dir, app_layout, verstr)["note"] == "renamed"

    capfd.readouterr()
    assert _snapshot(app_layout.app_name, action="show", version=verstr,
                     store=uri, as_json=True) == 0
    shown = json.loads(capfd.readouterr().out)
    assert shown["metadata"]["verstr"] == verstr
    assert "dirty" in shown["patches"]["working_tree"]

    assert _snapshot(app_layout.app_name, action="delete", version=verstr, store=uri) == 0
    assert _entries(_records_dir(store_dir, app_layout)) == []
    assert _entries(_code_dir(store_dir, app_layout)) == []


def test_configured_store_is_the_default_and_local_overrides(app_layout, capfd, store_dir):
    _bootstrap(app_layout)
    _configure_store(app_layout, _uri(store_dir))
    _dirty(app_layout, content="configured")
    remote = _create(app_layout, capfd)
    assert _entries(_records_dir(store_dir, app_layout)) == [remote]

    _dirty(app_layout, content="local only")
    local = _create(app_layout, capfd, local=True)
    assert _entries(_records_dir(local_store_root(app_layout.repo_path), app_layout)) == [local]
    assert _entries(_records_dir(store_dir, app_layout)) == [remote]

    capfd.readouterr()
    assert _snapshot(app_layout.app_name, action="list", as_json=True) == 0
    assert [r["verstr"] for r in json.loads(capfd.readouterr().out)] == [remote]


def test_env_store_is_used(app_layout, capfd, store_dir, monkeypatch):
    _bootstrap(app_layout)
    monkeypatch.setenv("VMN_EXPERIMENT_STORE", _uri(store_dir))
    _dirty(app_layout)
    verstr = _create(app_layout, capfd)
    assert _entries(_records_dir(store_dir, app_layout)) == [verstr]


def test_offline_mode_keeps_snapshots_local(app_layout, capfd, store_dir, monkeypatch):
    _bootstrap(app_layout)
    _configure_store(app_layout, _uri(store_dir))
    monkeypatch.setenv("VMN_EXP_OFFLINE", "1")
    _dirty(app_layout)
    verstr = _create(app_layout, capfd)
    assert _entries(_records_dir(local_store_root(app_layout.repo_path), app_layout)) == [verstr]
    assert _entries(_records_dir(store_dir, app_layout)) == []


def test_snapshot_shares_the_code_object_of_a_run(app_layout, capfd, store_dir):
    _bootstrap(app_layout)
    uri = _uri(store_dir)
    _dirty(app_layout, content="shared state")
    capfd.readouterr()
    assert _experiment(app_layout.app_name, extra_args=["--store", uri]) == 0
    code_keys = _entries(_code_dir(store_dir, app_layout))
    assert len(code_keys) == 1

    verstr = _create(app_layout, capfd, store=uri)
    assert _meta(store_dir, app_layout, verstr)["code"] == code_keys[0]
    assert _entries(_code_dir(store_dir, app_layout)) == code_keys

    assert _snapshot(app_layout.app_name, action="delete", version=verstr, store=uri) == 0
    assert _entries(_code_dir(store_dir, app_layout)) == code_keys


BUCKET = "snap-remote-bkt"


@pytest.fixture
def s3(monkeypatch):
    boto3 = pytest.importorskip("boto3")
    moto = pytest.importorskip("moto")
    for k, v in dict(AWS_ACCESS_KEY_ID="x", AWS_SECRET_ACCESS_KEY="x",
                     AWS_DEFAULT_REGION="us-east-1").items():
        monkeypatch.setenv(k, v)
    with moto.mock_aws():
        boto3.client("s3").create_bucket(Bucket=BUCKET)
        yield


def test_s3_store_serves_snapshots_a_checkout_does_not_hold(app_layout, capfd, s3):
    _bootstrap(app_layout)
    uri = f"s3://{BUCKET}"
    _dirty(app_layout, content="on s3")
    verstr = _create(app_layout, capfd, store=uri)
    shutil.rmtree(_records_dir(local_store_root(app_layout.repo_path), app_layout))
    shutil.rmtree(_code_dir(local_store_root(app_layout.repo_path), app_layout))

    capfd.readouterr()
    assert _snapshot(app_layout.app_name, action="show", version=verstr,
                     store=uri, as_json=True) == 0
    shown = json.loads(capfd.readouterr().out)
    assert "on s3" in shown["patches"]["working_tree"]
