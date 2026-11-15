"""Deletes on GCS and Azure (plan 41 D13): Azure sends a record's objects in
blob batch requests; GCS, whose batch endpoint fake-gcs-server does not
answer, sends its per-key deletes concurrently. A key the store refuses comes
back in ``delete_objects``' ``Errors`` so ``storage.delete`` raises."""
import logging
import threading

import pytest

from object_store_fakes import FakeContainerClient, FakeGCSClient, MatchConditions
from vmn_exp.storage.object_client import ObjectClient

APP = "trainer"
V1 = "1.2.0-dev.abc1234.0000001"


def _delete_request(keys):
    return {"Objects": [{"Key": k} for k in keys], "Quiet": True}


class _OneKeyFails(ObjectClient):
    def __init__(self):
        super().__init__()
        self.removed = []

    def _remove(self, key):
        if key == "b":
            raise RuntimeError("refused")
        self.removed.append(key)


def test_default_remove_many_reports_a_failed_key_in_errors():
    client = _OneKeyFails()

    resp = client.delete_objects("bkt", _delete_request(["a", "b", "c"]))

    assert resp == {"Errors": [{"Key": "b", "Message": "refused"}]}
    assert client.removed == ["a", "c"]


def _gcs_client(keys):
    from vmn_exp.storage.gcs import GCSObjectClient

    fake = FakeGCSClient()
    bucket = fake.bucket("bkt")
    for key in keys:
        bucket.blob(key).upload_from_string(b"x")
    return fake, GCSObjectClient(fake, "bkt")


def _azure_client(keys, container=None):
    from vmn_exp.storage.azure import AzureObjectClient

    fake = container or FakeContainerClient("bkt")
    for key in keys:
        fake.get_blob_client(key).upload_blob(b"x")
    return fake, AzureObjectClient(fake, MatchConditions.IfNotModified)


def _keys(n):
    return [f"k{i:04d}" for i in range(n)]


class _PairedDeletesBucket:
    """Each delete waits for a second one in flight: deletes sent one by one
    break the barrier (its timeout bounds the red case only)."""

    def __init__(self, bucket):
        self._bucket, self._pair = bucket, threading.Barrier(2, timeout=5)

    def __getattr__(self, name):
        return getattr(self._bucket, name)

    def delete_blob(self, blob_name):
        self._pair.wait()
        self._bucket.delete_blob(blob_name)


def test_gcs_delete_sends_the_per_key_deletes_concurrently():
    fake, client = _gcs_client(_keys(4))
    client._bucket = _PairedDeletesBucket(client._bucket)

    assert client.delete_objects("bkt", _delete_request(_keys(4))) == {"Errors": []}

    assert fake.bucket("bkt").objects == {}


def test_azure_delete_of_600_keys_uses_3_delete_blobs_calls():
    fake, client = _azure_client(_keys(600))

    assert client.delete_objects("bkt", _delete_request(_keys(600))) == {"Errors": []}

    assert fake.delete_blobs_calls == 3
    assert fake.objects == {}


@pytest.mark.parametrize("make", [_gcs_client, _azure_client])
def test_missing_key_in_a_batch_is_not_an_error(make):
    _, client = make(["present"])

    resp = client.delete_objects("bkt", _delete_request(["present", "missing"]))

    assert resp == {"Errors": []}


def _refusing_gcs_store():
    from vmn_exp.storage.gcs import GCSSnapshotStorage

    fake = FakeGCSClient()
    store = GCSSnapshotStorage("bkt", prefix="p", client=fake)
    return store, fake.bucket("bkt").refused_deletes


def _refusing_azure_store():
    from vmn_exp.storage.azure import AzureSnapshotStorage

    fake = FakeContainerClient("bkt")
    store = AzureSnapshotStorage("bkt", prefix="p", container=fake,
                                 if_not_modified=MatchConditions.IfNotModified)
    return store, fake.refused_deletes


@pytest.mark.parametrize("make", [_refusing_gcs_store, _refusing_azure_store])
def test_failed_key_in_a_batch_raises_from_storage_delete(make):
    store, refused = make()
    store.save(APP, V1, {"verstr": V1, "app": APP}, {"working_tree": "diff"})
    refused.update(k for k in _stored_keys(store) if k.endswith("working_tree.patch"))

    with pytest.raises(RuntimeError, match="refused to delete 1 objects"):
        store.delete(APP, V1)

    assert store.load_metadata(APP, V1) is None


def _stored_keys(store):
    return [o["Key"] for o in store._objects("p/")]


class _NoBatchContainer(FakeContainerClient):
    """An account that refuses blob batch (some account types do)."""

    def delete_blobs(self, *blobs, raise_on_any_failure=True):
        self.delete_blobs_calls += 1
        from object_store_fakes import HttpResponseError

        raise HttpResponseError(400)


def test_azure_batch_refusal_falls_back_to_per_key_deletes_with_a_warning(caplog):
    fake, client = _azure_client(_keys(3), container=_NoBatchContainer("bkt"))

    with caplog.at_level(logging.WARNING):
        resp = client.delete_objects("bkt", _delete_request(_keys(3)))

    assert resp == {"Errors": []}
    assert fake.objects == {}
    assert "one by one" in caplog.text


def test_fake_delete_blobs_is_absorbed_by_the_real_sdk_kwargs():
    import inspect

    from azure.storage.blob import ContainerClient

    real = inspect.signature(ContainerClient.delete_blobs).parameters.values()
    assert any(p.kind is inspect.Parameter.VAR_KEYWORD for p in real)
