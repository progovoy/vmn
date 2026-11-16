"""``store_errors(stores, action)``: an S3 client error raised while a snapshot
action runs on an s3:// store (after it opened) is a SnapshotStoreError naming
the action, the URI and the error; anything else passes through unchanged."""
from types import SimpleNamespace

import pytest

from s3_fakes import FakeS3Client, FakeS3Error
from version_stamp.snapshot import listing
from version_stamp.snapshot.load import load_snapshot
from version_stamp.snapshot.stores import (
    SnapshotStoreError,
    local_snapshot_stores,
    open_stores,
    store_errors,
)
from version_stamp.store import marker

URI = "s3://b/p"


@pytest.fixture(autouse=True)
def clean():
    marker.forget_checked()
    yield
    marker.forget_checked()


class EndpointConnectionError(Exception):
    """Shaped like botocore's: no ``response``, defined in ``botocore.exceptions``."""

    def __init__(self):
        super().__init__('Could not connect to the endpoint URL: "http://s3:9000/b"')


EndpointConnectionError.__module__ = "botocore.exceptions"

CONNECTION = (EndpointConnectionError,
              'EndpointConnectionError: Could not connect to the endpoint URL: "http://s3:9000/b"')
EXPIRED = (lambda: FakeS3Error("ExpiredToken", "The provided token has expired."),
           "FakeS3Error: ExpiredToken: The provided token has expired.")
ERRORS = pytest.mark.parametrize("make_error, message", [EXPIRED, CONNECTION],
                                 ids=["credentials", "connection"])


class FailingS3Client(FakeS3Client):
    """Fails the *nth* S3 call after :meth:`fail_on` with ``make_error()``."""

    fail_at = None

    def fail_on(self, nth, make_error):
        self.fail_at, self.make_error = len(self.calls) + nth, make_error

    def _record(self, op, kwargs):
        super()._record(op, kwargs)
        if self.fail_at is not None and len(self.calls) >= self.fail_at:
            raise self.make_error()


def _stores(client, read_only=False):
    vcs = SimpleNamespace(vmn_root_path="/nowhere", name="app", store={}, experiment={})
    return open_stores(vcs, {"store": URI, "read_only": read_only}, {}, lambda url: client,
                       lambda: 1767225600.0, lambda: 0.0, lambda sec: None)


def _seeded(client):
    stores = _stores(client)
    for v in ("0.0.1-dev.1", "0.0.1-dev.2", "0.0.1-dev.3"):
        stores.records.save("app", v, {"verstr": v, "timestamp": "2026-01-01T00:00:00Z"},
                            {"working_tree": "diff\n"})
    return _stores(client, read_only=True)


def _fails(stores, action, run, message):
    with pytest.raises(SnapshotStoreError) as exc:
        with store_errors(stores, action):
            run()
    assert str(exc.value) == f"snapshot {action} failed: {URI}: cannot reach the store: {message}"


@ERRORS
@pytest.mark.parametrize("nth", [1, 3])
def test_list_failing_mid_listing(make_error, message, nth):
    client = FailingS3Client()
    stores = _seeded(client)
    client.fail_on(nth, make_error)
    _fails(stores, "list", lambda: listing.snapshot_list(stores.records, "app"), message)


@ERRORS
@pytest.mark.parametrize("nth", [1, 2])
def test_show_failing_on_a_patch_or_metadata_get(make_error, message, nth):
    client = FailingS3Client()
    stores = _seeded(client)
    client.fail_on(nth, make_error)
    _fails(stores, "show", lambda: listing.snapshot_show(stores.records, "app", "0.0.1-dev.2"),
           message)


@ERRORS
def test_restore_failing_while_loading_the_record(make_error, message):
    client = FailingS3Client()
    stores = _seeded(client)
    client.fail_on(2, make_error)
    _fails(stores, "restore", lambda: load_snapshot(stores, "app", "0.0.1-dev.1", "restore"),
           message)


@ERRORS
@pytest.mark.parametrize("nth", [1, 2], ids=["patch-put", "metadata-put"])
def test_create_failing_mid_save(make_error, message, nth):
    client = FailingS3Client()
    stores = _stores(client)
    client.fail_on(nth, make_error)

    def save():
        stores.records.save("app", "0.0.1-dev.9", {"verstr": "0.0.1-dev.9"},
                            {"working_tree": "diff\n"})

    _fails(stores, "create", save, message)


def test_a_bug_on_an_s3_store_passes_through():
    stores = _stores(FailingS3Client())
    with pytest.raises(KeyError):
        with store_errors(stores, "list"):
            raise KeyError("bug")


def test_a_store_error_already_raised_passes_through():
    stores = _stores(FailingS3Client())
    with pytest.raises(SnapshotStoreError, match="^other$"):
        with store_errors(stores, "list"):
            raise SnapshotStoreError("other")


def test_directory_stores_pass_s3_shaped_errors_through(tmp_path):
    stores = local_snapshot_stores(str(tmp_path))
    with pytest.raises(FakeS3Error):
        with store_errors(stores, "list"):
            raise FakeS3Error("ExpiredToken")


def test_success_returns_normally():
    stores = _stores(FailingS3Client())
    with store_errors(stores, "list"):
        result = 0
    assert result == 0
