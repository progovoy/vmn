"""Experiment/snapshot records never carry a remote URL's credentials: stripped
when written, and redacted when an older record that has them is read (so the
UI, exports, reruns and pushes see clean values too)."""
import os

import pytest
import yaml
from exp_helpers import _bootstrap, _exp, _storage

from version_stamp.core import utils as vmn_utils
from vmn_exp import _base
from vmn_exp.core.index_store_schema import SCHEMA_VERSION
from vmn_exp.snapshot import LocalSnapshotStorage
from vmn_exp.storage.files import METADATA_FILE

TOKEN = "glpat-SECRET"
TOKEN_URL = f"https://oauth2:{TOKEN}@gitlab.example.com/group/repo.git"
CLEAN_URL = "https://gitlab.example.com/group/repo.git"
URLS = [
    TOKEN_URL, "https://u@h/x", "ssh://git:pw@h/x", "ssh://git@h/x", "git@h:x.git",
    "../rel", "file:///srv/r", "", None, 3, "https://h/p@v1", "https://u:p@ss@h/x",
]
RECORD = {
    "verstr": "0.0.1-dev.a.b",
    "timestamp": "2026-01-01T00:00:00Z",
    "remote": TOKEN_URL,
    "changesets": {".": {"hash": "h", "remote": TOKEN_URL}, "../d": {"hash": "d"}},
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_SNAPSHOT_METADATA"):
        monkeypatch.delenv(key, raising=False)


@pytest.mark.parametrize("url", URLS)
def test_strip_url_credentials_matches_vmn(url):
    assert _base.strip_url_credentials(url) == vmn_utils.strip_url_credentials(url)


@pytest.mark.parametrize("meta", [RECORD, None, {"verstr": "v"}, {"changesets": None}])
def test_redact_record_remotes_matches_vmn(meta):
    assert _base.redact_record_remotes(meta) == vmn_utils.redact_record_remotes(meta)


def test_parse_record_metadata_redacts_remotes():
    meta = _base.parse_record_metadata(yaml.dump(RECORD))
    assert meta["remote"] == CLEAN_URL
    assert meta["changesets"]["."]["remote"] == CLEAN_URL


def _assert_clean(meta):
    assert TOKEN not in str(meta)
    assert meta["remote"] == CLEAN_URL


def _raw_file(storage, app, verstr):
    path = os.path.join(storage.local_record_dir(app, verstr), METADATA_FILE)
    with open(path) as f:
        return f.read()


def test_local_storage_writes_records_without_credentials(tmp_path):
    storage = LocalSnapshotStorage(str(tmp_path))
    storage.save("app", RECORD["verstr"], dict(RECORD), {})
    assert TOKEN not in _raw_file(storage, "app", RECORD["verstr"])


def _write_old_record(storage, app):
    storage.save("app", RECORD["verstr"], {"verstr": RECORD["verstr"]}, {})
    path = os.path.join(storage.local_record_dir(app, RECORD["verstr"]), METADATA_FILE)
    with open(path, "w") as f:
        yaml.dump(dict(RECORD, format_version=2), f)


def test_local_storage_redacts_an_older_record_when_read(tmp_path):
    storage = LocalSnapshotStorage(str(tmp_path))
    _write_old_record(storage, "app")
    verstr = RECORD["verstr"]
    _assert_clean(storage.load_metadata("app", verstr))
    _assert_clean(storage.load_record("app", verstr)[0])
    _assert_clean(storage.load("app", verstr)[0])
    _assert_clean(storage.list_snapshots("app")[0])


def test_local_update_metadata_heals_an_older_record(tmp_path):
    storage = LocalSnapshotStorage(str(tmp_path))
    _write_old_record(storage, "app")
    storage.update_note("app", RECORD["verstr"], "n")
    assert TOKEN not in _raw_file(storage, "app", RECORD["verstr"])


def test_s3_storage_writes_and_reads_without_credentials(monkeypatch):
    from s3_helpers import BUCKET, mocked_bucket, s3_storage
    import boto3

    with mocked_bucket(monkeypatch):
        storage = s3_storage()
        storage.save("app", "v1", dict(RECORD, verstr="v1"), {})
        listed = boto3.client("s3").list_objects_v2(Bucket=BUCKET)["Contents"]
        key = next(o["Key"] for o in listed if o["Key"].endswith(f"v1/{METADATA_FILE}"))
        body = boto3.client("s3").get_object(Bucket=BUCKET, Key=key)["Body"].read()
        assert TOKEN.encode() not in body

        old = yaml.dump(dict(RECORD, verstr="v1", format_version=2))
        boto3.client("s3").put_object(Bucket=BUCKET, Key=key, Body=old.encode())
        _assert_clean(storage.load_record("app", "v1")[0])
        _assert_clean(storage.load_metadata("app", "v1"))
        _assert_clean(storage.list_snapshots("app")[0])


def test_git_free_run_from_an_exported_snapshot_has_no_credentials(tmp_path):
    from vmn_exp.core.from_snapshot import create_from_snapshot
    from vmn_exp.snapshot import open_storage

    meta_path = tmp_path / "vmn_metadata.yml"
    meta_path.write_text(yaml.dump({
        "verstr": "0.0.1-dev.abc.def", "app_name": "testapp", "base_version": "0.0.1",
        "base_commit": "abc", "remote": TOKEN_URL,
        "changesets": {".": {"hash": "abc", "remote": TOKEN_URL}},
    }))
    storage = open_storage(root=str(tmp_path / "exp"), area="runs")

    verstr, err = create_from_snapshot(storage, "testapp", str(meta_path))

    assert err is None
    assert TOKEN not in _raw_file(storage, "testapp", verstr)


def test_vmn_exp_create_records_the_remote_without_credentials(app_layout, monkeypatch):
    from version_stamp.backends import git_history

    _bootstrap(app_layout)
    monkeypatch.setattr(git_history.GitHistoryMixin, "remote", lambda self: TOKEN_URL)
    app_layout.write_file_commit_and_push("test_repo_0", "work.txt", "committed\n")
    with open(os.path.join(app_layout.repo_path, "work.txt"), "w") as f:
        f.write("dirty\n")

    assert _exp(app_layout.app_name) == 0

    storage = _storage(app_layout)
    (meta,) = storage.list_snapshots(app_layout.app_name)
    assert TOKEN not in _raw_file(storage, app_layout.app_name, meta["verstr"])
    assert meta["remote"] == CLEAN_URL


def test_ui_versions_serve_tag_changesets_without_credentials(tmp_path, monkeypatch):
    import git

    from vmn_exp.ui.readers import versions

    git.Repo.init(str(tmp_path))
    data = {"stamping": {"app": {"changesets": {".": {"hash": "h", "remote": TOKEN_URL}}}}}
    monkeypatch.setattr(
        versions, "_app_tags", lambda repo, prefix: [("app_0.0.1", data, "t")]
    )

    (row,) = versions.list_versions(str(tmp_path), "app")

    assert row["changesets"]["."]["remote"] == CLEAN_URL


def test_index_schema_bumped_so_cached_rows_with_credentials_are_dropped():
    assert SCHEMA_VERSION != "exp-index-17"
