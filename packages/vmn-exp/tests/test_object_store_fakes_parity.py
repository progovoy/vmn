"""The GCS/Azure fakes in object_store_fakes.py against the real SDKs: a fake
may accept only parameters the real method accepts, and storage/gcs.py may
pass only keywords the real SDK names (plan 41 D15 stage 1).

GCS names every parameter, so the GCS check is by signature. Azure takes most
options through ``**kwargs``; its table lists, per method, the fake parameters
the real signature does not name. Those are checked only to be absorbed by a
real ``**kwargs``, and the emulator runs (D15 stage 2) are the check with
authority for them:

- ``BlobClient.upload_blob``: ``overwrite``, ``etag``, ``match_condition``
- ``BlobClient.download_blob``: none (``offset``, ``length`` are named)
- ``ContainerClient.list_blobs``, ``walk_blobs``, ``delete_blob``,
  ``get_blob_client``, ``from_connection_string``: none
- ``BlobClient.get_blob_properties``: none (takes only ``**kwargs``)
"""
import ast
import inspect
import pathlib

import object_store_fakes as fakes

_VAR = (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
_GCS_PY = (pathlib.Path(__file__).resolve().parents[2]
           / "vmn-exp-sdk/src/vmn_exp/storage/gcs.py")


def _named(func):
    params = inspect.signature(func).parameters.values()
    return {p.name for p in params if p.kind not in _VAR and p.name != "self"}


def _takes_kwargs(func):
    params = inspect.signature(func).parameters.values()
    return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params)


def _gcs_table():
    from google.cloud import storage
    return {
        fakes.FakeBlob.upload_from_string: storage.Blob.upload_from_string,
        fakes.FakeBlob.upload_from_filename: storage.Blob.upload_from_filename,
        fakes.FakeBlob.download_as_bytes: storage.Blob.download_as_bytes,
        fakes.FakeBlob.download_to_filename: storage.Blob.download_to_filename,
        fakes.FakeBlob.open: storage.Blob.open,
        fakes.FakeGCSBucket.blob: storage.Bucket.blob,
        fakes.FakeGCSBucket.get_blob: storage.Bucket.get_blob,
        fakes.FakeGCSBucket.delete_blob: storage.Bucket.delete_blob,
        fakes.FakeGCSClient.bucket: storage.Client.bucket,
        fakes.FakeGCSClient.list_blobs: storage.Client.list_blobs,
    }


def _azure_table():
    from azure.storage.blob import BlobClient, ContainerClient
    return {
        fakes.FakeBlobClient.get_blob_properties: (BlobClient.get_blob_properties, set()),
        fakes.FakeBlobClient.upload_blob: (
            BlobClient.upload_blob, {"overwrite", "etag", "match_condition"}),
        fakes.FakeBlobClient.download_blob: (BlobClient.download_blob, set()),
        fakes.FakeContainerClient.from_connection_string: (
            ContainerClient.from_connection_string, set()),
        fakes.FakeContainerClient.get_blob_client: (ContainerClient.get_blob_client, set()),
        fakes.FakeContainerClient.list_blobs: (ContainerClient.list_blobs, set()),
        fakes.FakeContainerClient.walk_blobs: (ContainerClient.walk_blobs, set()),
        fakes.FakeContainerClient.delete_blob: (ContainerClient.delete_blob, set()),
    }


def test_fake_gcs_methods_accept_only_real_sdk_parameters():
    drift = {fake.__qualname__: sorted(_named(fake) - _named(real))
             for fake, real in _gcs_table().items()}
    assert {k: v for k, v in drift.items() if v} == {}


def test_fake_azure_methods_accept_only_real_sdk_parameters():
    drift = {}
    for fake, (real, kwargs_only) in _azure_table().items():
        extra = _named(fake) - _named(real)
        if extra != kwargs_only or (extra and not _takes_kwargs(real)):
            drift[fake.__qualname__] = sorted(extra)
    assert drift == {}


def _gcs_sdk_methods():
    from google.cloud import storage
    return {
        "upload_from_string": storage.Blob.upload_from_string,
        "upload_from_filename": storage.Blob.upload_from_filename,
        "download_as_bytes": storage.Blob.download_as_bytes,
        "download_to_filename": storage.Blob.download_to_filename,
        "open": storage.Blob.open,
        "blob": storage.Bucket.blob,
        "get_blob": storage.Bucket.get_blob,
        "delete_blob": storage.Bucket.delete_blob,
        "bucket": storage.Client.bucket,
        "list_blobs": storage.Client.list_blobs,
        "Client": storage.Client.__init__,
    }


def _called_name(call):
    func = call.func
    return func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)


def test_gcs_storage_code_passes_only_keywords_the_real_sdk_accepts():
    methods = _gcs_sdk_methods()
    tree = ast.parse(_GCS_PY.read_text())
    checked, wrong = set(), {}
    for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
        real = methods.get(_called_name(call))
        keywords = {k.arg for k in call.keywords if k.arg}
        if real is None or not keywords:
            continue
        checked.add(_called_name(call))
        unknown = keywords - _named(real)
        if unknown:
            wrong[f"{_called_name(call)}:{call.lineno}"] = sorted(unknown)
    assert wrong == {}
    assert {"upload_from_string", "download_as_bytes", "list_blobs", "Client"} <= checked
