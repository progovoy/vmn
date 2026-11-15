"""Azure listings resume server-side (plan 41 D14): an azure-storage-blob
whose List Blobs operation sends ``start_from`` lets a listing start past a
key, so a walk jumps past a subtree and ``list_files_between`` answers. The
service's start key is inclusive, so the key itself is filtered client-side,
which is also the whole of the fallback for an SDK without it."""
from object_store_fakes import FakeContainerClient, MatchConditions
from s3_helpers import meta
from vmn_exp.storage import azure
from vmn_exp.storage.azure import AzureObjectClient, AzureSnapshotStorage

APP = "app"


def _client(supports_start_from):
    container = FakeContainerClient()
    for key in ("a", "b", "c"):
        container.get_blob_client(key).upload_blob(b"x")
    client = AzureObjectClient(container, MatchConditions.IfNotModified,
                               supports_start_from=supports_start_from)
    return container, client


def _keys(page):
    return [obj["Key"] for obj in page["Contents"]]


def test_iter_passes_the_start_key_when_supported():
    container, client = _client(supports_start_from=True)

    page = client.list_objects_v2(Bucket="c", Prefix="", StartAfter="a")

    assert container.list_blobs_kwargs == [{"start_from": "a"}]
    assert _keys(page) == ["b", "c"]
    assert client.server_side_start_after is True


def test_iter_filters_client_side_when_unsupported():
    container, client = _client(supports_start_from=False)

    page = client.list_objects_v2(Bucket="c", Prefix="", StartAfter="a")

    assert container.list_blobs_kwargs == [{}]
    assert _keys(page) == ["b", "c"]
    assert client.server_side_start_after is False


def test_start_key_itself_is_never_returned():
    _, client = _client(supports_start_from=True)

    page = client.list_objects_v2(Bucket="c", Prefix="", StartAfter="b")

    assert _keys(page) == ["c"]


def _store(supports_start_from):
    store = AzureSnapshotStorage("c", container=FakeContainerClient(),
                                 if_not_modified=MatchConditions.IfNotModified,
                                 supports_start_from=supports_start_from)
    for verstr in ("0.1", "0.2", "0.3"):
        store.save(APP, verstr, meta(verstr), {})
        store.save_file(APP, verstr, "run_state.yml", "state: running\n")
    return store


def test_list_files_between_answers_when_the_start_key_is_supported():
    store = _store(supports_start_from=True)
    names = ["0.1", "0.2", "0.3"]

    assert store.list_files_between(APP, names) == store.list_files(APP, keys=names)
    assert _store(supports_start_from=False).list_files_between(APP, names) is None


def test_the_installed_sdk_sends_start_from():
    assert azure.sdk_sends_start_from() is True


def test_an_operation_without_start_from_is_not_supported():
    def list_blob_flat_segment(prefix=None, marker=None, **kwargs):
        pass

    assert azure.takes_start_from(list_blob_flat_segment) is False
