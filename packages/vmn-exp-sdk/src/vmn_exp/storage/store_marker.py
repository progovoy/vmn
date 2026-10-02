"""``store.yml``: the marker at a store root (docs/plans/14-store-layout.md §2.3).

The first writer creates it with a create-if-absent put (``O_EXCL``-style
link locally, ``If-None-Match`` on object stores). Writers and readers refuse
a root of an unknown ``layout`` and a v1 root (vmn records, no marker);
writers also refuse while ``migrating`` is set.
"""
import datetime
import os
import tempfile
import threading

import yaml

from vmn_exp.storage import areas

MARKER = "store.yml"
LAYOUT = 2
_AREAS = {areas.RUNS, areas.SNAPSHOTS, areas.CODE, areas.SWEEPS, areas.REGISTRY,
          areas.REPORTS, areas.COMMENTS, areas.JOURNAL}

_checked = set()
_lock = threading.Lock()


class StoreLayoutError(ValueError):
    pass


class MissingStoreError(ValueError):
    pass


def forget_checked():
    with _lock:
        _checked.clear()


def new_marker():
    now = datetime.datetime.now(datetime.timezone.utc)
    return {"layout": LAYOUT, "created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "journal": {"partition": "minute"}}


class LocalRoot:
    def __init__(self, root):
        self.root = root
        self.key = ("file", os.path.abspath(root))

    def _path(self):
        return os.path.join(self.root, MARKER)

    def read(self):
        try:
            with open(self._path()) as f:
                return f.read()
        except FileNotFoundError:
            return None

    def create(self, text):
        os.makedirs(self.root, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.root, prefix=".store.yml.")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(text)
            os.link(tmp, self._path())
        except FileExistsError:
            pass
        finally:
            os.unlink(tmp)

    def entries(self):
        try:
            return set(os.listdir(self.root))
        except FileNotFoundError:
            return set()


class ObjectRoot:
    def __init__(self, client, bucket, prefix, endpoint_url=None):
        self.client, self.bucket, self.prefix = client, bucket, prefix
        self.key = ("object", type(client).__name__, endpoint_url, bucket, prefix)
        self._dir = f"{prefix}/" if prefix else ""

    def _key(self):
        return self._dir + MARKER

    def read(self):
        from vmn_exp.storage.s3_base import is_missing

        try:
            body = self.client.get_object(Bucket=self.bucket, Key=self._key())
        except Exception as e:
            if is_missing(e):
                return None
            raise
        return body["Body"].read().decode()

    def create(self, text):
        from vmn_exp.storage.s3_base import is_taken

        try:
            self.client.put_object(Bucket=self.bucket, Key=self._key(),
                                   Body=text.encode(), IfNoneMatch="*")
        except Exception as e:
            if not is_taken(e):
                raise

    def entries(self):
        page = self.client.list_objects_v2(
            Bucket=self.bucket, Prefix=self._dir, Delimiter="/", MaxKeys=100)
        names = [p["Prefix"] for p in page.get("CommonPrefixes", [])]
        names += [o["Key"] for o in page.get("Contents", [])]
        return {n[len(self._dir):].rstrip("/") for n in names}


def root_of(storage):
    """The marker location of a backend storage, or None (unknown backend)."""
    if hasattr(storage, "root") and hasattr(storage, "area"):
        return LocalRoot(storage.root)
    client = getattr(storage, "_s3", None)
    if client is None:
        return None
    return ObjectRoot(client, storage.bucket, storage.prefix.rpartition("/")[0],
                      getattr(storage, "endpoint_url", None))


def _has_records(where):
    return any(n not in _AREAS and n != MARKER and not n.startswith(".")
               for n in where.entries())


def _parse(text):
    marker = yaml.safe_load(text) if text else None
    return marker if isinstance(marker, dict) else {}


def check_store(storage, writer):
    """Refuse *storage*'s root if it isn't a usable layout-2 store; a writer
    creates the marker when absent. Checked once per root and mode."""
    where = root_of(storage)
    if where is None:
        return
    cache_key = (where.key, writer)
    with _lock:
        if cache_key in _checked:
            return
    _check(where, writer)
    with _lock:
        _checked.add(cache_key)


def _check(where, writer):
    text = where.read()
    if text is None:
        if _has_records(where):
            raise StoreLayoutError(
                f"{_label(where)} is a v1 store (records but no {MARKER}): "
                "run `vmn-exp migrate`")
        if not writer:
            return
        where.create(yaml.safe_dump(new_marker(), sort_keys=False))
        text = where.read()
    marker = _parse(text)
    if marker.get("layout") != LAYOUT:
        raise StoreLayoutError(
            f"{_label(where)} has store layout {marker.get('layout')}; this vmn-exp "
            f"knows layout {LAYOUT} only: upgrade vmn-exp")
    if writer and marker.get("migrating"):
        raise StoreLayoutError(
            f"{_label(where)} is migrating (`vmn-exp migrate`): retry when it is done")


def _label(where):
    if isinstance(where, LocalRoot):
        return where.root
    return f"{where.bucket}/{where.prefix}"


def require_store(storage, uri=None):
    """The reader's check of *storage*'s root: StoreLayoutError when it is
    unusable and, given its *uri*, MissingStoreError when it holds no vmn
    store at all."""
    backend = _backend(storage)
    where = root_of(backend)
    if where is None:
        return
    if uri and where.read() is None and not any(
            not n.startswith(".") for n in where.entries()):
        raise MissingStoreError(f"no vmn store at {uri}")
    check_store(backend, writer=False)


def _backend(storage):
    """The storage that holds the authoritative records (the remote, if any)."""
    return getattr(storage, "_remote", None) or getattr(storage, "_local", None) or storage
