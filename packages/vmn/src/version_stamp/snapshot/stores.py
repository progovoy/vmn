"""Which stores a snapshot command reads and writes.

``SnapshotStores(records, code, where, runs=None)``: *records* holds snapshot
records, *code* the code objects they reference, *where* names the store for
messages (``"local"`` or a store URI), *runs* the experiment runs that may
reference code too (None: no runs are scanned).

``open_stores(vcs, params, env, s3_client_factory, now, monotonic, sleep)``:

1. ``params["local"]``: the repo-local stores;
2. the opener registered through :func:`.opener.register_snapshot_store_opener`
   (vmn-exp), ``opener(vcs, params) -> SnapshotStores | None``, wins when it
   returns stores;
3. the store :func:`version_stamp.store.config.resolve_store` names from the
   flags, *env* (``VMN_STORE*``, ``VMN_EXPERIMENT_*``) and the app conf
   (``store``, ``experiment.storage``): ``s3://`` (*s3_client_factory*) or a
   directory (``file://``). A writer creates the root's ``store.yml``
   (*now*/*monotonic*/*sleep*); a reader (``params["read_only"]``) refuses a
   root holding no store. An s3:// store that can't be reached while its root
   is checked (credentials, network) is a :class:`SnapshotStoreError` naming
   the URI and the error. Other schemes need vmn-exp (:class:`SnapshotStoreError`);
4. nothing configured: the repo-local stores.

``store_errors(stores, action)``: a context manager turning an S3 client
error (:func:`version_stamp.store.s3_errors.is_client_error`) raised while
*action* runs on s3:// *stores* into a :class:`SnapshotStoreError`
``"snapshot <action> failed: <uri>: cannot reach the store: <error>"``.

``open_snapshot_stores(vcs, params)``: :func:`open_stores` with the real
environment, boto3 and clocks of :func:`version_stamp.core.real_io.real_store_io`
(the ``version_stamp.api`` entry vmn-exp uses).

``local_snapshot_stores(vmn_root_path) -> SnapshotStores``: records in
``.vmn/store/snapshots/<app-key>/``, code in ``.vmn/store/code/<app-key>/``
(shared with the runs of ``.vmn/store/runs/<app-key>/``).
"""
from contextlib import contextmanager
from dataclasses import dataclass

from version_stamp.core.real_io import real_store_io
from version_stamp.snapshot import opener as snapshot_opener
from version_stamp.snapshot.local_store import LocalRecordStore
from version_stamp.store import marker
from version_stamp.store.config import resolve_store
from version_stamp.store.open import UnsupportedScheme, open_record_stores
from version_stamp.store.s3_errors import is_client_error

NEEDS_EXP = "{scheme}:// snapshot stores need vmn-exp: pip install vmn-exp"
S3_NEEDS_EXTRA = "s3:// snapshot stores need boto3: pip install 'vmn[s3]'"
UNREACHABLE = "{uri}: cannot reach the store: {error}"


class SnapshotStoreError(RuntimeError):
    pass


@dataclass
class SnapshotStores:
    records: object
    code: object
    where: str
    runs: object = None


def local_snapshot_stores(vmn_root_path):
    code = LocalRecordStore(vmn_root_path, "code")
    records = LocalRecordStore(vmn_root_path, "snapshots", code_store=code)
    runs = LocalRecordStore(vmn_root_path, "runs", code_store=code)
    return SnapshotStores(records=records, code=code, where="local", runs=runs)


def _opened_by_plugin(vcs, params):
    opener = snapshot_opener.snapshot_store_opener()
    return None if opener is None else opener(vcs, params)


def _app_conf(vcs):
    return {"store": getattr(vcs, "store", None) or {},
            "experiment": getattr(vcs, "experiment", None) or {}}


def _record_stores(uri, options, s3_client_factory):
    try:
        records, code, runs = open_record_stores(uri, options, s3_client_factory,
                                                 LocalRecordStore.at_root)
    except UnsupportedScheme as exc:
        raise SnapshotStoreError(NEEDS_EXP.format(scheme=exc.scheme)) from None
    except ImportError:
        raise SnapshotStoreError(S3_NEEDS_EXTRA) from None
    return SnapshotStores(records=records, code=code, where=uri, runs=runs)


def _unreachable(uri, exc):
    return UNREACHABLE.format(uri=uri, error=f"{type(exc).__name__}: {exc}")


def _check_root(records, params, uri, now, monotonic, sleep):
    if params.get("read_only"):
        marker.require_store(records, uri)
    else:
        marker.check_store(records, writer=True, now=now, monotonic=monotonic, sleep=sleep)


def _check_reachable_root(records, params, uri, now, monotonic, sleep):
    """:func:`_check_root`, with an s3:// store's credentials or network error
    (anything but the marker's own ValueErrors) as a SnapshotStoreError."""
    try:
        _check_root(records, params, uri, now, monotonic, sleep)
    except ValueError:
        raise
    except Exception as exc:
        if not uri.startswith("s3://"):
            raise
        raise SnapshotStoreError(_unreachable(uri, exc)) from None


def _configured_stores(vcs, params, env, s3_client_factory, now, monotonic, sleep):
    uri, options = resolve_store(params, env, _app_conf(vcs))
    if uri is None:
        return None
    stores = _record_stores(uri, options, s3_client_factory)
    _check_reachable_root(stores.records, params, uri, now, monotonic, sleep)
    return stores


def open_stores(vcs, params, env, s3_client_factory, now, monotonic, sleep):
    if params.get("local"):
        return local_snapshot_stores(vcs.vmn_root_path)
    stores = _opened_by_plugin(vcs, params) or _configured_stores(
        vcs, params, env, s3_client_factory, now, monotonic, sleep)
    return stores or local_snapshot_stores(vcs.vmn_root_path)


@contextmanager
def store_errors(stores, action):
    """An S3 client error of snapshot *action* on an s3:// *stores* as a
    SnapshotStoreError saying the action failed; other errors unchanged."""
    try:
        yield
    except Exception as exc:
        if not (stores.where.startswith("s3://") and is_client_error(exc)):
            raise
        raise SnapshotStoreError(
            f"snapshot {action} failed: {_unreachable(stores.where, exc)}") from None


def open_snapshot_stores(vcs, params):
    return open_stores(vcs, params, **real_store_io())
