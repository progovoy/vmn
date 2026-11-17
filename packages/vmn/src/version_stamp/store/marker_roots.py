"""Where a ``store.yml`` lives: a directory (:class:`LocalRoot`) or an object
store prefix (:class:`ObjectRoot`). Each reads the marker, creates it if
absent, and lists the root's entries for the v1 check (:mod:`.marker`)."""
import os
import re
import tempfile

from version_stamp.core.constants import VMN_VERSTR_REGEX
from version_stamp.core.utils import yaml_safe_load
from version_stamp.store import areas
from version_stamp.store.names import is_record_metadata, read_file, unsafe_verstr
from version_stamp.store.s3_errors import is_missing, is_taken

MARKER = "store.yml"
_V1_CONTAINERS = ("experiments", "snapshots")
_V1_PREFIXES = ("vmn-experiments", "vmn-snapshots")
RECORD_FILE = "metadata.yml"
_RECORDS_PROBED = 5  # record prefixes of a top-level name probed on object stores
_VERSTR_START = re.compile(VMN_VERSTR_REGEX)
_POLL_SEC = 0.01


def is_record_name(name):
    """Whether *name* (record form: ``_plus_`` for ``+``) names a vmn verstr:
    it starts with ``VMN_VERSTR_REGEX`` (``X.Y.Z[.hotfix][-prerelease.rcn]``)
    and goes on, if at all, with ``.``, ``-`` or ``+`` (a dev, build or v1
    suffix, e.g. ``1.2.0-dev.a1b2c3d.e4f5a6b``, ``0.0.1.dev.abc``)."""
    verstr = unsafe_verstr(name)
    match = _VERSTR_START.match(verstr)
    return bool(match) and verstr[match.end():match.end() + 1] in ("", ".", "-", "+")


def _publish_locked(path, tmp, monotonic, sleep, wait_sec=30.0):
    """Publish *tmp* as *path* unless it exists — for filesystems without hard
    links. An exclusive ``mkdir`` elects the one creator, which publishes with
    an atomic rename, so no reader ever sees a partial marker; a loser waits
    (``sleep``, up to *wait_sec* of ``monotonic`` time) for the winner's marker."""
    lock = os.path.join(os.path.dirname(path), f".{os.path.basename(path)}.lock")
    try:
        os.mkdir(lock)
    except FileExistsError:
        deadline = monotonic() + wait_sec
        while not os.path.exists(path) and monotonic() < deadline:
            sleep(_POLL_SEC)
        return
    try:
        if not os.path.exists(path):
            os.replace(tmp, path)
    finally:
        os.rmdir(lock)


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

    def create(self, text, monotonic, sleep):
        os.makedirs(self.root, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.root, prefix=".store.yml.")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(text)
            os.chmod(tmp, 0o644)
            os.link(tmp, self._path())
        except FileExistsError:
            pass
        except OSError:
            _publish_locked(self._path(), tmp, monotonic, sleep)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def entries(self):
        try:
            return set(os.listdir(self.root))
        except FileNotFoundError:
            return set()

    def dirs(self):
        return {n for n in self.entries() if os.path.isdir(os.path.join(self.root, n))}

    def holds_records(self, name):
        """Whether ``<root>/<name>/`` holds a v1 record: a subdirectory named
        like a verstr (even with no files), or one with a ``metadata.yml``."""
        top = os.path.join(self.root, name)
        return any(_local_record(os.path.join(top, rec)) for rec in os.listdir(top))

    def _v1_dirs(self):
        """The ``.vmn`` dirs v1 kept this root's records in: ``<root>/.vmn``
        (``--dir``/``file://``) and, for the repo-local ``.vmn/store``, its parent."""
        root = os.path.abspath(self.root)
        parent = os.path.dirname(root)
        found = [os.path.join(root, ".vmn")]
        if os.path.basename(root) == "store" and os.path.basename(parent) == ".vmn":
            found.append(parent)
        return found

    def has_v1_records(self):
        skip = os.path.abspath(self.root)
        return any(_v1_local_record(d, skip) for d in self._v1_dirs())


def _local_record(path):
    if not os.path.isdir(path):
        return False
    return is_record_name(os.path.basename(path)) or os.path.isfile(
        os.path.join(path, RECORD_FILE))


def _is_v1_record_dir(path):
    """A v1 record directory: its ``metadata.yml`` is a record's, not a stamp
    snapshot's (``create_snapshots`` writes those to ``.vmn/<app>/snapshots/``)."""
    raw = read_file(os.path.join(path, RECORD_FILE))
    return raw is not None and is_record_metadata(yaml_safe_load(raw))


def _v1_local_record(vmn_dir, skip):
    """Whether *vmn_dir* holds a v1 record: ``<app path>/{experiments,snapshots}/<rec>/metadata.yml``."""
    for path, dirs, _files in os.walk(vmn_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".")
                   and os.path.join(path, d) != skip]
        if path == vmn_dir or os.path.basename(path) not in _V1_CONTAINERS:
            continue
        if any(_is_v1_record_dir(os.path.join(path, d)) for d in dirs):
            return True
        dirs[:] = []
    return False


class ObjectRoot:
    def __init__(self, storage, bucket, prefix, endpoint_url=None):
        self._storage, self.bucket, self.prefix = storage, bucket, prefix
        self.key = ("object", type(self.client).__name__, endpoint_url, bucket, prefix)
        self._dir = f"{prefix}/" if prefix else ""

    @property
    def client(self):
        """The storage's client of this process (a forked child's own)."""
        return self._storage._s3

    def _key(self):
        return self._dir + MARKER

    def read(self):
        try:
            body = self.client.get_object(Bucket=self.bucket, Key=self._key())
        except Exception as e:
            if is_missing(e):
                return None
            raise
        return body["Body"].read().decode()

    def create(self, text, monotonic, sleep):
        try:
            self.client.put_object(Bucket=self.bucket, Key=self._key(),
                                   Body=text.encode(), IfNoneMatch="*")
        except Exception as e:
            if not is_taken(e):
                raise

    def _page(self):
        return self.client.list_objects_v2(
            Bucket=self.bucket, Prefix=self._dir, Delimiter="/", MaxKeys=100)

    def _names(self, keys):
        return {k[len(self._dir):].rstrip("/") for k in keys}

    def entries(self):
        page = self._page()
        return self.dirs(page) | self._names(o["Key"] for o in page.get("Contents", []))

    def dirs(self, page=None):
        page = page or self._page()
        return self._names(p["Prefix"] for p in page.get("CommonPrefixes", []))

    def holds_records(self, name):
        """Whether ``<root>/<name>/`` holds a v1 record: a ``<verstr>/`` prefix,
        or one of the first few prefixes with a ``metadata.yml``."""
        return self._holds_records(f"{self._dir}{name}/")

    def _subdirs(self, top):
        """The first few ``<top><name>/`` prefixes."""
        page = self.client.list_objects_v2(
            Bucket=self.bucket, Prefix=top, Delimiter="/", MaxKeys=_RECORDS_PROBED)
        return [p["Prefix"] for p in page.get("CommonPrefixes", [])]

    def _holds_records(self, top):
        return any(self._is_record(rec) for rec in self._subdirs(top))

    def _is_record(self, rec):
        if is_record_name(rec.rstrip("/").rpartition("/")[2]):
            return True
        return bool(self.client.list_objects_v2(
            Bucket=self.bucket, Prefix=rec + RECORD_FILE, MaxKeys=1).get("Contents"))

    def has_v1_records(self):
        """A path-less URI's v1 records were under the default v1 prefixes,
        ``<prefix>/<app-key>/<verstr>/metadata.yml``."""
        if self.prefix != areas.DEFAULT_ROOT:
            return False
        return any(self._holds_records(app)
                   for p in _V1_PREFIXES for app in self._subdirs(f"{p}/"))
