"""v1 data outside the new root is refused with the migrate hint
(docs/plans/14-store-layout.md §2.3, §4): the repo-local ``.vmn/<app>/...``
dirs and the default object-store prefixes."""
import os

import boto3
import pytest

from s3_helpers import BUCKET, mocked_bucket
from vmn_exp.storage import store_marker
from vmn_exp.storage.open import open_storage
from vmn_exp.storage.store_marker import StoreLayoutError
from vmn_exp.storage.uri import s3_uri


@pytest.fixture(autouse=True)
def _fresh_cache():
    store_marker.forget_checked()
    yield
    store_marker.forget_checked()


def _touch(path, text="verstr: x\n"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def _refused(where, root):
    for writer in (True, False):
        store_marker.forget_checked()
        with pytest.raises(StoreLayoutError, match="vmn-exp migrate"):
            storage = open_storage(where, root, area="runs", writer=writer)
            store_marker.require_store(storage)
    assert not os.path.exists(os.path.join(root, "store.yml")) if root else True


@pytest.mark.parametrize("v1_dir", [
    "my/app/experiments/r1",
    "my/app/snapshots/s1",
    "vmn-code/my~app/experiments/c1.abc",
    "vmn-registry/experiments/m1",
])
def test_repo_local_v1_records_refused(tmp_path, v1_dir):
    _touch(str(tmp_path / ".vmn" / v1_dir / "metadata.yml"))
    _refused(None, str(tmp_path / ".vmn" / "store"))


def test_dir_store_v1_records_refused(tmp_path):
    _touch(str(tmp_path / "dir" / ".vmn" / "my" / "app" / "experiments" / "r1" / "metadata.yml"))
    _refused(None, str(tmp_path / "dir"))


def test_repo_local_conf_files_are_no_records(tmp_path):
    _touch(str(tmp_path / ".vmn" / "my" / "app" / "conf.yml"))
    _touch(str(tmp_path / ".vmn" / "my" / "app" / "experiments" / ".gitignore"), "*\n")
    _touch(str(tmp_path / ".vmn" / "my" / "app" / "snapshots" / "s1" / "notes.txt"))
    root = str(tmp_path / ".vmn" / "store")
    open_storage(None, root, area="runs")
    assert os.path.exists(os.path.join(root, "store.yml"))


@pytest.mark.parametrize("prefix", ["vmn-experiments", "vmn-snapshots"])
def test_default_object_prefixes_refused(monkeypatch, prefix):
    with mocked_bucket(monkeypatch):
        client = boto3.client("s3")
        client.put_object(Bucket=BUCKET, Key=f"{prefix}/my-app/r1/metadata.yml", Body=b"x")
        with pytest.raises(StoreLayoutError, match="vmn-exp migrate"):
            open_storage(s3_uri(BUCKET), area="runs")
        listed = client.list_objects_v2(Bucket=BUCKET, Prefix="vmn/")
        assert listed.get("KeyCount", 0) == 0
