"""The Google Cloud Storage backend (``gs://bucket/prefix``,
``pip install 'vmn-exp-sdk[gcs]'``).

The S3 backend's logic over a google-cloud-storage bucket: the object
generation is the ETag, so ``if_generation_match=0`` is the atomic
``If-None-Match: *`` create and ``if_generation_match=<generation>`` the
``If-Match`` overwrite. Credentials come from Application Default Credentials.
"""
from vmn_exp.storage.object_client import (
    BAD_RANGE,
    MISSING,
    Body,
    ObjectClient,
    ObjectStoreError,
)
from vmn_exp.storage.registry import default_prefix, missing_extra
from vmn_exp.storage.s3 import S3SnapshotStorage


def _obj(blob):
    return {"Key": blob.name, "Size": blob.size, "LastModified": blob.updated,
            "ETag": str(blob.generation)}


class GCSObjectClient(ObjectClient):
    def __init__(self, client, bucket):
        super().__init__()
        self._client = client
        self._bucket = client.bucket(bucket)

    def _stat(self, key):
        blob = self._bucket.get_blob(key)
        return _obj(blob) if blob is not None else None

    def _existing(self, key):
        blob = self._bucket.get_blob(key)
        if blob is None:
            raise ObjectStoreError(MISSING, key)
        return blob

    def _get(self, key, offset):
        blob = self._existing(key)
        if offset and offset >= blob.size:
            raise ObjectStoreError(BAD_RANGE, key)
        # The generation read first: a newer object under an older token only
        # makes a conditional write retry.
        return {
            "Body": Body(lambda: blob.download_as_bytes(start=offset or None),
                         lambda size: _chunks(blob, size)),
            "ETag": str(blob.generation),
            "ContentLength": blob.size - offset,
        }

    def _put(self, key, body, if_none_match, if_match):
        data = body.encode("utf-8") if isinstance(body, str) else body
        condition = 0 if if_none_match else (int(if_match) if if_match else None)
        self._bucket.blob(key).upload_from_string(data, if_generation_match=condition)

    def _iter(self, prefix, delimiter, start_after):
        listing = self._client.list_blobs(
            self._bucket, prefix=prefix or None, delimiter=delimiter,
            start_offset=start_after or None,
        )
        seen = set()
        for page in listing.pages:
            for blob in page:
                if blob.name > start_after:
                    yield _obj(blob)
            for p in sorted(set(page.prefixes) - seen):
                seen.add(p)
                if p > start_after:
                    yield p

    def _remove(self, key):
        try:
            self._bucket.delete_blob(key)
        except Exception as e:
            if getattr(e, "code", None) != 404:
                raise

    def _upload(self, src, key):
        self._bucket.blob(key).upload_from_filename(src)

    def _download(self, key, dest):
        self._bucket.blob(key).download_to_filename(dest)


def _chunks(blob, size):
    with blob.open("rb") as f:
        yield from iter(lambda: f.read(size), b"")


class GCSSnapshotStorage(S3SnapshotStorage):
    scheme = "gs"

    def __init__(self, bucket, prefix="vmn-snapshots", client=None):
        if client is None:
            client = _default_client()
        super().__init__(bucket, prefix=prefix, client=GCSObjectClient(client, bucket))


def _default_client(endpoint_url=None):
    try:
        from google.cloud import storage
    except ImportError:
        raise missing_extra("google-cloud-storage", "gcs") from None
    if endpoint_url:
        return storage.Client(client_options={"api_endpoint": endpoint_url})
    return storage.Client()


def open_gcs_store(uri, subdir):
    client = _default_client(uri.options.get("endpoint_url"))
    return GCSSnapshotStorage(uri.location, prefix=default_prefix(uri, subdir),
                              client=client)
