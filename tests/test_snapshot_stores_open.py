"""``open_stores(vcs, params, env, s3_client_factory, now, monotonic, sleep)``:
``--local``, then a registered opener, then the configured store (flags,
``VMN_STORE*``, conf), else the repo-local stores; s3:// and directories built in."""
import os
from types import SimpleNamespace

import pytest

from s3_fakes import FakeS3Client, FakeS3Error
from version_stamp.cli import plugin_api
from version_stamp.snapshot import opener as snapshot_opener
from version_stamp.snapshot.stores import SnapshotStoreError, SnapshotStores, open_stores
from version_stamp.store import marker


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setattr(snapshot_opener, "_snapshot_store_opener", None)
    marker.forget_checked()
    yield
    marker.forget_checked()


class FakeFactory:
    def __init__(self):
        self.client = FakeS3Client()
        self.endpoints = []

    def __call__(self, endpoint_url):
        self.endpoints.append(endpoint_url)
        return self.client


def _no_boto3(endpoint_url):
    raise ImportError("No module named 'boto3'")


def _vcs(tmp_path, store=None, experiment=None):
    return SimpleNamespace(vmn_root_path=str(tmp_path), name="app",
                           store=store or {}, experiment=experiment or {})


def _open(vcs, params=None, env=None, factory=None):
    return open_stores(vcs, params or {}, env or {}, factory or FakeFactory(),
                       lambda: 1767225600.0, lambda: 0.0, lambda sec: None)


def test_store_flag_s3_opens_the_three_areas(tmp_path):
    factory = FakeFactory()
    stores = _open(_vcs(tmp_path), {"store": "s3://b/p"}, factory=factory)
    assert stores.where == "s3://b/p"
    assert (stores.records.prefix, stores.code.prefix, stores.runs.prefix) == (
        "p/snapshots", "p/code", "p/runs")
    assert stores.records.code_store is stores.code
    stores.records.save("app", "v1", {"verstr": "v1"}, {})
    assert "p/snapshots/app/v1/metadata.yml" in factory.client.keys("b")


def test_vmn_store_beats_vmn_experiment_store_beats_conf(tmp_path):
    vcs = _vcs(tmp_path, store={"uri": "s3://conf/c"})
    env = {"VMN_STORE": "s3://new/n", "VMN_EXPERIMENT_STORE": "s3://old/o"}
    assert _open(vcs, env=env).where == "s3://new/n"
    assert _open(vcs, env={"VMN_EXPERIMENT_STORE": "s3://old/o"}).where == "s3://old/o"
    assert _open(vcs).where == "s3://conf/c"


def test_legacy_experiment_storage_conf_is_read(tmp_path):
    vcs = _vcs(tmp_path, experiment={"storage": {"bucket": "legacy"}})
    assert _open(vcs).where == "s3://legacy/vmn"


def test_offline_uses_the_local_stores(tmp_path):
    env = {"VMN_STORE": "s3://b/p", "VMN_EXP_OFFLINE": "1"}
    assert _open(_vcs(tmp_path), env=env).where == "local"


def test_local_flag_wins(tmp_path):
    factory = FakeFactory()
    stores = _open(_vcs(tmp_path), {"local": True, "store": "s3://b/p"},
                   {"VMN_STORE": "s3://b/p"}, factory)
    assert stores.where == "local" and factory.endpoints == []


def test_nothing_configured_is_local(tmp_path):
    assert _open(_vcs(tmp_path)).where == "local"


def test_other_schemes_need_vmn_exp(tmp_path):
    with pytest.raises(SnapshotStoreError,
                       match=r"^gs:// snapshot stores need vmn-exp: pip install vmn-exp$"):
        _open(_vcs(tmp_path), {"store": "gs://bucket/prefix"})


def test_registered_opener_is_asked_first(tmp_path):
    opened = SnapshotStores(records="r", code="c", where="gs://b/p")
    plugin_api.register_snapshot_store_opener(lambda vcs, params: opened)
    factory = FakeFactory()
    assert _open(_vcs(tmp_path), env={"VMN_STORE": "s3://b/p"}, factory=factory) is opened
    assert factory.endpoints == []


def test_opener_returning_none_falls_back_to_the_configured_store(tmp_path):
    plugin_api.register_snapshot_store_opener(lambda vcs, params: None)
    assert _open(_vcs(tmp_path), env={"VMN_STORE": "s3://b/p"}).where == "s3://b/p"


def test_a_reader_refuses_an_empty_store(tmp_path):
    with pytest.raises(ValueError, match="no vmn store at s3://b/p"):
        _open(_vcs(tmp_path), {"store": "s3://b/p", "read_only": True})


def test_a_writer_creates_store_yml_once(tmp_path):
    factory = FakeFactory()
    _open(_vcs(tmp_path), {"store": "s3://b/p"}, factory=factory)
    marker.forget_checked()
    _open(_vcs(tmp_path), {"store": "s3://b/p"}, factory=factory)
    created = [put for put in factory.client.ops("put_object") if put["Key"] == "p/store.yml"]
    assert len(created) == 1
    _open(_vcs(tmp_path), {"store": "s3://b/p", "read_only": True}, factory=factory)


def test_file_store_round_trip(tmp_path):
    root = tmp_path / "shared"
    uri = f"file://{root}"
    stores = _open(_vcs(tmp_path / "repo"), {"store": uri})
    assert stores.where == uri
    stores.code.save("app", "k", {"verstr": "k"}, {"working_tree": "diff\n"})
    stores.records.save("app", "v1", {"verstr": "v1", "code": "k"}, {})
    assert os.path.isfile(root / "store.yml")
    reader = _open(_vcs(tmp_path / "other"), {"store": uri, "read_only": True})
    metadata, patches = reader.records.load("app", "v1")
    assert metadata["verstr"] == "v1" and patches == {"working_tree": "diff\n"}


def test_missing_boto3_names_the_vmn_s3_extra(tmp_path):
    with pytest.raises(SnapshotStoreError, match=r"pip install 'vmn\[s3\]'"):
        _open(_vcs(tmp_path), {"store": "s3://b/p"}, factory=_no_boto3)


class NoCredentialsError(Exception):
    """Shaped like botocore's: no ``response``."""

    def __init__(self):
        super().__init__("Unable to locate credentials")


class EndpointConnectionError(Exception):
    def __init__(self):
        super().__init__('Could not connect to the endpoint URL: "http://s3:9000/b"')


class UnreachableS3Client(FakeS3Client):
    def __init__(self, error):
        super().__init__()
        self.error = error

    def get_object(self, Bucket, Key, Range=None):
        raise self.error

    def list_objects_v2(self, *args, **kwargs):
        raise self.error


@pytest.mark.parametrize("read_only", [False, True])
@pytest.mark.parametrize("error, message", [
    (NoCredentialsError(), "NoCredentialsError: Unable to locate credentials"),
    (EndpointConnectionError(),
     'EndpointConnectionError: Could not connect to the endpoint URL: "http://s3:9000/b"'),
])
def test_an_unreachable_s3_store_is_a_store_error(tmp_path, error, message, read_only):
    factory = FakeFactory()
    factory.client = UnreachableS3Client(error)
    with pytest.raises(SnapshotStoreError) as exc:
        _open(_vcs(tmp_path), {"store": "s3://b/p", "read_only": read_only}, factory=factory)
    assert str(exc.value) == f"s3://b/p: cannot reach the store: {message}"


@pytest.mark.parametrize("read_only", [False, True])
@pytest.mark.parametrize("code, text", [
    ("AccessDenied", "Access Denied"),
    ("InvalidAccessKeyId", "The AWS Access Key Id you provided does not exist in our records."),
    ("ExpiredToken", "The provided token has expired."),
])
def test_a_store_that_refuses_the_request_says_so(tmp_path, code, text, read_only):
    error = FakeS3Error(code)
    error.response["Error"]["Message"] = text
    factory = FakeFactory()
    factory.client = UnreachableS3Client(error)
    with pytest.raises(SnapshotStoreError) as exc:
        _open(_vcs(tmp_path), {"store": "s3://b/p", "read_only": read_only}, factory=factory)
    assert str(exc.value) == f"s3://b/p: the store refused the request: {code}: {text}"
