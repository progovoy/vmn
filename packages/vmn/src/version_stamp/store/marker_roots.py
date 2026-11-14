"""Where a ``store.yml`` lives: a directory (:class:`LocalRoot`) or an object
store prefix (:class:`ObjectRoot`). Each reads the marker, creates it if
absent, and lists the root's entries for the v1 check (:mod:`.marker`)."""
import os
import tempfile

from version_stamp.store import areas
from version_stamp.store.s3_errors import is_missing, is_taken

MARKER = "store.yml"
_V1_CONTAINERS = ("experiments", "snapshots")
_V1_PREFIXES = ("vmn-experiments", "vmn-snapshots")
_POLL_SEC = 0.01


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


def _v1_local_record(vmn_dir, skip):
    """Whether *vmn_dir* holds a v1 record: ``<app path>/{experiments,snapshots}/<rec>/metadata.yml``."""
    for path, dirs, _files in os.walk(vmn_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".")
                   and os.path.join(path, d) != skip]
        if path == vmn_dir or os.path.basename(path) not in _V1_CONTAINERS:
            continue
        if any(os.path.isfile(os.path.join(path, d, "metadata.yml")) for d in dirs):
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

    def has_v1_records(self):
        """A path-less URI's v1 records were under the default v1 prefixes."""
        if self.prefix != areas.DEFAULT_ROOT:
            return False
        return any(self.client.list_objects_v2(
            Bucket=self.bucket, Prefix=f"{p}/", MaxKeys=1).get("Contents")
            for p in _V1_PREFIXES)
