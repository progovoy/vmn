"""store.yml at a store root (docs/plans/14-store-layout.md §2.3)."""
import errno
import os
import threading
import time

import boto3
import pytest
import yaml
from s3_helpers import BUCKET, PREFIX, mocked_bucket
from vmn_exp.storage.open import open_storage
from vmn_exp.storage.store_marker import StoreLayoutError
from vmn_exp.storage.uri import s3_uri

from vmn_exp.storage import store_marker


@pytest.fixture(autouse=True)
def _fresh_cache():
    store_marker.forget_checked()
    yield
    store_marker.forget_checked()


def _read_local(root):
    with open(os.path.join(root, "store.yml")) as f:
        return yaml.safe_load(f)


def _read_s3():
    body = boto3.client("s3").get_object(Bucket=BUCKET, Key=f"{PREFIX}/store.yml")
    return yaml.safe_load(body["Body"].read())


def _race(fn, n=8):
    barrier = threading.Barrier(n)
    errors = []

    def go():
        barrier.wait()
        try:
            fn()
        except Exception as e:  # pragma: no cover - reported below
            errors.append(e)

    threads = [threading.Thread(target=go) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []


def _open_checked(root, writer):
    """Open as a writer, or as a reader that then reads (checks lazily)."""
    storage = open_storage(None, root, area="runs", writer=writer)
    if not writer:
        store_marker.require_store(storage)
    return storage


def test_reader_checks_lazily(tmp_path):
    root = tmp_path / "store"
    root.mkdir()
    (root / "store.yml").write_text("layout: 7\n")
    open_storage(None, str(root), area="runs", writer=False)


def test_writer_creates_local_marker(tmp_path):
    root = str(tmp_path / "store")
    open_storage(None, root, area="runs")
    marker = _read_local(root)
    assert marker["layout"] == 2
    assert marker["journal"] == {"partition": "minute"}
    assert marker["created_at"]


def test_local_marker_is_readable_by_other_users(tmp_path):
    root = str(tmp_path / "store")
    open_storage(None, root, area="runs")
    mode = os.stat(os.path.join(root, "store.yml")).st_mode & 0o777
    assert mode & 0o044 == 0o044


def test_local_marker_created_once_under_race(tmp_path):
    root = str(tmp_path / "store")
    seen = []

    def open_one():
        store_marker.forget_checked()
        open_storage(None, root, area="runs")
        seen.append(_read_local(root)["created_at"])

    _race(open_one)
    assert len(set(seen)) == 1


def test_s3_marker_created_once_under_race(monkeypatch):
    with mocked_bucket(monkeypatch):
        seen = []

        def open_one():
            store_marker.forget_checked()
            open_storage(s3_uri(BUCKET, PREFIX), area="runs")
            seen.append(_read_s3()["created_at"])

        _race(open_one)
        assert len(set(seen)) == 1
        assert _read_s3()["layout"] == 2


def test_reader_does_not_create_marker(tmp_path):
    root = str(tmp_path / "store")
    open_storage(None, root, area="runs", writer=False)
    assert not os.path.exists(os.path.join(root, "store.yml"))


def test_unknown_layout_refused(tmp_path):
    root = tmp_path / "store"
    root.mkdir()
    (root / "store.yml").write_text("layout: 7\n")
    for writer in (True, False):
        store_marker.forget_checked()
        with pytest.raises(StoreLayoutError, match="layout 7"):
            _open_checked(str(root), writer)


def test_v1_store_refused_with_migrate_hint(tmp_path):
    root = tmp_path / "store"
    (root / "my_app" / "0.0.1.dev.abc").mkdir(parents=True)
    for writer in (True, False):
        store_marker.forget_checked()
        with pytest.raises(StoreLayoutError, match="vmn-exp migrate"):
            _open_checked(str(root), writer)


def test_v1_s3_store_refused(monkeypatch):
    with mocked_bucket(monkeypatch):
        boto3.client("s3").put_object(
            Bucket=BUCKET, Key=f"{PREFIX}/my_app/v1/metadata.yml", Body=b"x"
        )
        with pytest.raises(StoreLayoutError, match="vmn-exp migrate"):
            open_storage(s3_uri(BUCKET, PREFIX), area="runs")


def test_v2_areas_without_marker_are_adopted(tmp_path):
    root = tmp_path / "store"
    (root / "snapshots" / "app").mkdir(parents=True)
    open_storage(None, str(root), area="runs")
    assert _read_local(str(root))["layout"] == 2


def test_migrating_refuses_writers_not_readers(tmp_path):
    root = tmp_path / "store"
    root.mkdir()
    (root / "store.yml").write_text("layout: 2\nmigrating: true\n")
    with pytest.raises(StoreLayoutError, match="migrat"):
        open_storage(None, str(root), area="runs")
    store_marker.forget_checked()
    _open_checked(str(root), writer=False)


def test_missing_store_message(tmp_path, monkeypatch):
    with mocked_bucket(monkeypatch):
        uri = s3_uri(BUCKET, PREFIX)
        storage = open_storage(uri, area="runs", writer=False)
        with pytest.raises(store_marker.MissingStoreError) as exc:
            store_marker.require_store(storage, uri)
        assert str(exc.value) == f"no vmn store at {uri}"
        open_storage(uri, area="runs")
        store_marker.require_store(open_storage(uri, area="runs", writer=False), uri)


def _no_hard_links(monkeypatch, err):
    def link(src, dst):
        raise OSError(err, os.strerror(err))

    monkeypatch.setattr(os, "link", link)


@pytest.mark.parametrize("err", [errno.EPERM, errno.ENOTSUP])
def test_local_marker_without_hard_links(tmp_path, monkeypatch, err):
    _no_hard_links(monkeypatch, err)
    root = str(tmp_path / "store")
    open_storage(None, root, area="runs")
    assert _read_local(root)["layout"] == 2
    assert os.stat(os.path.join(root, "store.yml")).st_mode & 0o044 == 0o044
    assert os.listdir(root) == ["store.yml"]


def test_local_marker_without_hard_links_created_once_under_race(tmp_path, monkeypatch):
    _no_hard_links(monkeypatch, errno.EPERM)
    root = str(tmp_path / "store")
    seen = []

    def open_one():
        store_marker.forget_checked()
        open_storage(None, root, area="runs")
        seen.append(_read_local(root)["created_at"])

    _race(open_one)
    assert len(set(seen)) == 1


def test_slow_creator_without_hard_links_never_exposes_an_empty_marker(tmp_path, monkeypatch):
    _no_hard_links(monkeypatch, errno.EPERM)
    replace = os.replace

    def slow_replace(src, dst):
        time.sleep(2.5)
        replace(src, dst)

    monkeypatch.setattr(os, "replace", slow_replace)
    root = str(tmp_path / "store")
    seen = []

    def open_one():
        store_marker.forget_checked()
        open_storage(None, root, area="runs")
        seen.append(_read_local(root)["created_at"])

    _race(open_one, n=4)
    assert len(set(seen)) == 1
    assert os.listdir(root) == ["store.yml"]
