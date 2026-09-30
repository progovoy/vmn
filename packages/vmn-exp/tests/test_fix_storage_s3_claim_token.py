"""``create_exclusive(claim_token=)``: the ``.claim`` object carries the
claimer's token, so a claimer that crashed before writing the metadata can
resume its own claim — and nobody else's (S3, GCS and Azure alike)."""
import pytest
from s3_helpers import mocked_bucket, s3_storage

from object_store_fakes import FakeContainerClient, FakeGCSClient, MatchConditions
from vmn_exp.storage.s3_records import CLAIM_FILE

APP = "app"
X = "0.0.1-dev.abc1234.0000001"
PATCHES = {"working_tree": "diff --git a b\n"}


def _gcs():
    from vmn_exp.storage.gcs import GCSSnapshotStorage

    return GCSSnapshotStorage("bkt", prefix="p", client=FakeGCSClient())


def _azure():
    from vmn_exp.storage.azure import AzureSnapshotStorage

    return AzureSnapshotStorage(
        "bkt", prefix="p", container=FakeContainerClient("bkt"),
        if_not_modified=MatchConditions.IfNotModified,
    )


@pytest.fixture(params=["s3", "gs", "az"])
def store(request, monkeypatch):
    if request.param == "s3":
        with mocked_bucket(monkeypatch):
            yield s3_storage()
    else:
        yield {"gs": _gcs, "az": _azure}[request.param]()


def _meta(**kw):
    return dict({"verstr": X, "timestamp": "2026-01-01T00:00:00Z"}, **kw)


def _claim_key(store):
    return f"{store._key_prefix(APP, X)}/{CLAIM_FILE}"


def _crashed_claim(store, body):
    """A claim whose owner died before writing the body and metadata."""
    store._put(_claim_key(store), body)


def test_claim_body_is_the_token(store):
    assert store.create_exclusive(APP, X, _meta(), {}, claim_token="tok-1")
    assert store._get(_claim_key(store)) == b"tok-1"


def test_claim_token_resumes_own_crashed_claim(store):
    _crashed_claim(store, b"tok-1")
    assert store.create_exclusive(APP, X, _meta(), PATCHES, claim_token="tok-1")
    meta, patches = store.load_record(APP, X)
    assert meta["verstr"] == X and patches["working_tree"] == PATCHES["working_tree"]


def test_claim_token_mismatch_is_taken(store):
    _crashed_claim(store, b"someone-else")
    assert not store.create_exclusive(APP, X, _meta(), {}, claim_token="tok-1")
    assert store.load_metadata(APP, X) is None


def test_empty_claim_is_taken_even_with_token(store):
    _crashed_claim(store, b"")
    assert not store.create_exclusive(APP, X, _meta(), {}, claim_token="tok-1")


def test_existing_metadata_is_taken_even_with_matching_token(store):
    assert store.create_exclusive(APP, X, _meta(note="first"), {}, claim_token="tok-1")
    assert not store.create_exclusive(APP, X, _meta(note="again"), {},
                                      claim_token="tok-1")
    assert store.load_metadata(APP, X)["note"] == "first"


def test_without_token_the_claim_stays_empty(store):
    assert store.create_exclusive(APP, X, _meta(), {})
    assert store._get(_claim_key(store)) == b""
