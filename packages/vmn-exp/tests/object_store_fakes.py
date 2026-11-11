"""In-memory fakes of the google-cloud-storage and azure-storage-blob client
objects vmn's GCS/Azure backends call — same method names, arguments (kept
in step with the real SDKs by test_object_store_fakes_parity.py),
precondition semantics and exception ``code``/``status_code`` attributes.

Listings page two items at a time so paging paths are exercised.
"""
import datetime
import io
import itertools
import sys
import threading
import types

_PAGE = 2
_clock = itertools.count(1)


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


class _Obj:
    def __init__(self, data):
        self.data = bytes(data)
        self.generation = next(_clock)
        self.updated = _now()


def _as_bytes(data):
    if hasattr(data, "read"):
        data = data.read()
    return data.encode("utf-8") if isinstance(data, str) else bytes(data)


# -- google-cloud-storage -------------------------------------------------------


class NotFound(Exception):
    code = 404


class PreconditionFailed(Exception):
    code = 412


class RequestRangeNotSatisfiable(Exception):
    code = 416


class Forbidden(Exception):
    code = 403


class FakeBlob:
    def __init__(self, bucket, name, obj=None):
        self.bucket, self.name = bucket, name
        self.size = len(obj.data) if obj else None
        self.generation = obj.generation if obj else None
        self.updated = obj.updated if obj else None
        self.etag = f"etag-{self.generation}" if obj else None

    def _current(self):
        obj = self.bucket.objects.get(self.name)
        if obj is None:
            raise NotFound(self.name)
        return obj

    def upload_from_string(self, data, if_generation_match=None):
        with self.bucket.lock:
            cur = self.bucket.objects.get(self.name)
            generation = cur.generation if cur else 0
            if if_generation_match is not None and if_generation_match != generation:
                raise PreconditionFailed(self.name)
            obj = self.bucket.objects[self.name] = _Obj(_as_bytes(data))
            self.generation = obj.generation  # as the SDK does, from the response

    def upload_from_filename(self, filename):
        with open(filename, "rb") as f:
            self.upload_from_string(f.read())

    def download_as_bytes(self, start=None, end=None):
        obj = self._current()
        if start and start >= len(obj.data):
            raise RequestRangeNotSatisfiable(self.name)
        self.generation = obj.generation  # as the SDK does, from x-goog-generation
        return obj.data[start or 0:None if end is None else end + 1]

    def download_to_filename(self, filename):
        with open(filename, "wb") as f:
            f.write(self._current().data)

    def open(self, mode="rb"):
        assert mode == "rb"
        return io.BytesIO(self._current().data)


class _Page(list):
    prefixes = ()


class _Iterator:
    def __init__(self, items, prefixes):
        self._items, self._prefixes = items, prefixes

    @property
    def pages(self):
        for i in range(0, max(len(self._items), 1), _PAGE):
            page = _Page(self._items[i:i + _PAGE])
            page.prefixes = tuple(self._prefixes) if i == 0 else ()
            yield page

    def __iter__(self):
        for page in self.pages:
            yield from page


class FakeGCSBucket:
    def __init__(self, name):
        self.name = name
        self.objects = {}
        self.refused_deletes = set()
        self.lock = threading.Lock()

    def blob(self, blob_name):
        return FakeBlob(self, blob_name)

    def get_blob(self, blob_name):
        obj = self.objects.get(blob_name)
        return FakeBlob(self, blob_name, obj) if obj else None

    def delete_blob(self, blob_name):
        if blob_name in self.refused_deletes:
            raise Forbidden(blob_name)
        if self.objects.pop(blob_name, None) is None:
            raise NotFound(blob_name)


class FakeGCSClient:
    def __init__(self, *args, **kwargs):
        self.buckets = {}

    def bucket(self, bucket_name):
        return self.buckets.setdefault(bucket_name, FakeGCSBucket(bucket_name))

    def list_blobs(self, bucket_or_name, prefix=None, delimiter=None,
                   start_offset=None, max_results=None):
        bucket = bucket_or_name
        if isinstance(bucket, str):
            bucket = self.bucket(bucket)
        items, prefixes = [], []
        for name in sorted(bucket.objects):
            if prefix and not name.startswith(prefix):
                continue
            if start_offset and name < start_offset:  # inclusive, as GCS is
                continue
            rest = name[len(prefix or ""):]
            if delimiter and delimiter in rest:
                p = (prefix or "") + rest.split(delimiter)[0] + delimiter
                if p not in prefixes:
                    prefixes.append(p)
                continue
            items.append(FakeBlob(bucket, name, bucket.objects[name]))
        if max_results is not None:
            items = items[:max_results]
        return _Iterator(items, prefixes)


def install_fake_gcs(monkeypatch, client):
    """Make ``from google.cloud import storage`` yield a module whose
    ``Client()`` is *client*."""
    storage = types.ModuleType("google.cloud.storage")
    storage.Client = lambda *a, **k: client
    cloud = types.ModuleType("google.cloud")
    cloud.storage = storage
    google = types.ModuleType("google")
    google.cloud = cloud
    for name, mod in (("google", google), ("google.cloud", cloud),
                      ("google.cloud.storage", storage)):
        monkeypatch.setitem(sys.modules, name, mod)


# -- azure-storage-blob -----------------------------------------------------------


class ResourceNotFoundError(Exception):
    status_code = 404


class ResourceExistsError(Exception):
    status_code = 409


class ResourceModifiedError(Exception):
    status_code = 412


class HttpResponseError(Exception):
    def __init__(self, status_code):
        super().__init__(status_code)
        self.status_code = status_code


class _SubResponse:
    def __init__(self, status_code):
        self.status_code = status_code


class MatchConditions:
    IfNotModified = "if-not-modified"


class BlobProperties:
    def __init__(self, name, obj):
        self.name, self.size = name, len(obj.data)
        self.etag = f'"0x{obj.generation:X}"'
        self.last_modified = obj.updated


class BlobPrefix:
    def __init__(self, prefix):
        self.name = self.prefix = prefix


class _Downloader:
    def __init__(self, props, data):
        self.properties, self.size, self._data = props, props.size, data

    def readall(self):
        return self._data

    def readinto(self, stream):
        stream.write(self._data)
        return len(self._data)

    def chunks(self):
        for i in range(0, len(self._data), 3):
            yield self._data[i:i + 3]


class FakeBlobClient:
    def __init__(self, container, name):
        self.container, self.blob_name = container, name

    def _current(self):
        obj = self.container.objects.get(self.blob_name)
        if obj is None:
            raise ResourceNotFoundError(self.blob_name)
        return obj

    def get_blob_properties(self):
        return BlobProperties(self.blob_name, self._current())

    def upload_blob(self, data, overwrite=False, etag=None, match_condition=None):
        with self.container.lock:
            cur = self.container.objects.get(self.blob_name)
            if match_condition == MatchConditions.IfNotModified:
                if cur is None or BlobProperties(self.blob_name, cur).etag != etag:
                    raise ResourceModifiedError(self.blob_name)
            elif cur is not None and not overwrite:
                raise ResourceExistsError(self.blob_name)
            obj = self.container.objects[self.blob_name] = _Obj(_as_bytes(data))
            return {"etag": BlobProperties(self.blob_name, obj).etag}

    def download_blob(self, offset=None, length=None):
        obj = self._current()
        if offset and offset >= len(obj.data):
            raise HttpResponseError(416)
        start = offset or 0
        stop = None if length is None else start + length
        return _Downloader(BlobProperties(self.blob_name, obj), obj.data[start:stop])


class FakeContainerClient:
    _MAX_BATCH = 256

    def __init__(self, name="c"):
        self.container_name = name
        self.objects = {}
        self.refused_deletes = set()
        self.delete_blobs_calls = 0
        self.list_blobs_kwargs = []
        self.lock = threading.Lock()

    @classmethod
    def from_connection_string(cls, conn_str, container_name):
        return cls(container_name)

    def get_blob_client(self, blob):
        return FakeBlobClient(self, blob)

    def _names(self, prefix):
        return [n for n in sorted(self.objects) if n.startswith(prefix or "")]

    def list_blobs(self, name_starts_with=None, **kwargs):
        """``start_from`` is inclusive, as the service's ``startFrom``."""
        self.list_blobs_kwargs.append(kwargs)
        start = kwargs.get("start_from") or ""
        for name in self._names(name_starts_with):
            if name >= start:
                yield BlobProperties(name, self.objects[name])

    def walk_blobs(self, name_starts_with=None, delimiter="/"):
        seen = set()
        for name in self._names(name_starts_with):
            rest = name[len(name_starts_with or ""):]
            if delimiter in rest:
                p = (name_starts_with or "") + rest.split(delimiter)[0] + delimiter
                if p not in seen:
                    seen.add(p)
                    yield BlobPrefix(p)
                continue
            yield BlobProperties(name, self.objects[name])

    def delete_blob(self, blob):
        if blob in self.refused_deletes:
            raise HttpResponseError(403)
        if self.objects.pop(blob, None) is None:
            raise ResourceNotFoundError(blob)

    def delete_blobs(self, *blobs, raise_on_any_failure=True):
        """One batch request; an iterator of sub-responses, as the SDK returns."""
        if len(blobs) > self._MAX_BATCH:
            raise HttpResponseError(400)
        self.delete_blobs_calls += 1
        responses = [_SubResponse(self._delete_status(b)) for b in blobs]
        if raise_on_any_failure and any(r.status_code >= 300 for r in responses):
            raise HttpResponseError(207)
        return iter(responses)

    def _delete_status(self, blob):
        try:
            self.delete_blob(blob)
        except (HttpResponseError, ResourceNotFoundError) as e:
            return e.status_code
        return 202


def install_fake_azure(monkeypatch, container_cls=FakeContainerClient):
    blob = types.ModuleType("azure.storage.blob")
    blob.ContainerClient = container_cls
    core = types.ModuleType("azure.core")
    core.MatchConditions = MatchConditions
    storage = types.ModuleType("azure.storage")
    storage.blob = blob
    azure = types.ModuleType("azure")
    azure.storage, azure.core = storage, core
    for name, mod in (("azure", azure), ("azure.storage", storage),
                      ("azure.storage.blob", blob), ("azure.core", core)):
        monkeypatch.setitem(sys.modules, name, mod)
