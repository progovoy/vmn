"""The push ledger: what ``vmn exp push`` last sent of each run to one remote.

One YAML file per run at ``.vmn/<app>/experiments/.push/<remote_id>/<safe
verstr>.yml``. The dot-dir is skipped by listings, and the storage dir's
``.gitignore`` of ``*`` already covers it. Fields:

- ``remote_verstr``, ``identity`` (:func:`run_identity`), ``fingerprint``
  (:func:`record_fingerprint` after the push), ``complete``, ``pushed_at``;
- ``code_key``, ``code_pushed``;
- ``fields``: the last synced ``archived``/``note`` (the three-way base);
- ``files``: ``{name: {sha256, etag}}`` of the top-level files pushed;
- ``log_bytes``: ``{writer: bytes the remote holds}``;
- ``pending_target``: reserved for a rename in flight (WT5).

A complete entry whose fingerprint matches the run makes a push of it cost
no remote call.
"""
import hashlib
import os

import yaml

from vmn_exp import _base
from vmn_exp.storage.files import atomic_write, safe_verstr

PUSH_DIR = ".push"


def remote_id(target):
    """A short stable name for *target*'s data (its ``cache_identity()``,
    which includes the scheme)."""
    return hashlib.sha256(repr(target.cache_identity()).encode()).hexdigest()[:16]


class PushLedger:
    """``PushLedger(local, app_name, remote_id)``: ``get(verstr)`` -> entry
    dict or None, ``put(verstr, entry)``, ``delete(verstr)``; ``dir`` and
    ``lock_path`` (where a push holds its lock)."""

    def __init__(self, local, app_name, remote_id):
        self._local = local
        self._app_name = app_name
        self.dir = os.path.join(
            local._snapshot_base_dir(app_name), PUSH_DIR, remote_id
        )

    @classmethod
    def for_target(cls, local, app_name, target):
        return cls(local, app_name, remote_id(target))

    @property
    def lock_path(self):
        return os.path.join(self.dir, ".lock")

    def _path(self, verstr):
        return os.path.join(self.dir, safe_verstr(verstr) + ".yml")

    def get(self, verstr):
        try:
            with open(self._path(verstr), "rb") as f:
                entry = _base.yaml_safe_load(f)
        except FileNotFoundError:
            return None
        return entry if isinstance(entry, dict) else None

    def put(self, verstr, entry):
        self._local._ensure_base_dir(self._app_name)
        os.makedirs(self.dir, exist_ok=True)
        atomic_write(self._path(verstr), yaml.safe_dump(entry, sort_keys=True))

    def delete(self, verstr):
        try:
            os.unlink(self._path(verstr))
        except FileNotFoundError:
            pass
