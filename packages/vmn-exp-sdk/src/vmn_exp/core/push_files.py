"""A run's files other than its logs, for ``vmn exp push``.

- Top-level files (``env.yml``, ``run_state.yml``, ``alerts_sent.yml``, a
  legacy ``log.yml``, ...) go by sha256 against the ledger. ``run_state.yml``
  is never clobbered when the remote copy changed since this host last pushed
  it (its ETag differs from the ledger's); ``alerts_sent.yml`` is merged as a
  set union on both sides.
- Stored files (``artifacts/`` and ``outputs/``) go when missing remotely or
  of a different size.
- The mutable metadata fields ``archived``/``note`` merge three-way against
  the ledger's base; on a conflict (or without a base) the remote wins, with
  a warning, and the local copy takes the merged value.
"""
import hashlib

from vmn_exp.core.alerts.transitions import ALERTS_FILE, load_sent, save_sent
from vmn_exp.core.status import RUN_STATE_FILE
from vmn_exp.storage.files import METADATA_FILE, PATCH_FILES, is_log_file

MERGED_FIELDS = ("archived", "note")
_BODY_FILES = {METADATA_FILE} | {filename for _, filename, _ in PATCH_FILES}


def _sha(data):
    data = data.encode("utf-8") if isinstance(data, str) else data
    return hashlib.sha256(data).hexdigest()


def pushable_files(local, app_name, verstr):
    """The local record's top-level files push sends by content."""
    return sorted(
        name for name in local.record_files(app_name, verstr)
        if name not in _BODY_FILES and not is_log_file(name)
    )


def push_files(local, target, app_name, verstr, base_files):
    """``(files, warnings)``: *files* is the ledger's ``{name: {sha256[,
    etag]}}`` — an entry without ``etag`` was just written, and takes the
    ETag of the final listing. *base_files* is the previous ``files``."""
    pusher = _FilePusher(local, target, app_name, verstr)
    files = {}
    for name in pushable_files(local, app_name, verstr):
        base = (base_files or {}).get(name)
        files[name] = pusher.push(name, base)
    return files, pusher.warnings


class _FilePusher:
    def __init__(self, local, target, app_name, verstr):
        self._local, self._target = local, target
        self._at = (app_name, verstr)
        self._remote_files = None
        self.warnings = []

    def push(self, name, base):
        data = self._local.load_file(*self._at, name)
        if base and base.get("sha256") == _sha(data):
            return base
        if name == ALERTS_FILE:
            return {"sha256": _sha(self._merge_alerts())}
        if name == RUN_STATE_FILE and self._changed_elsewhere(name, data, base):
            self.warnings.append(
                f"{RUN_STATE_FILE} changed on the remote since the last push: "
                "not overwritten"
            )
            return base or {"sha256": None, "etag": None}
        self._target.save_file(*self._at, name, data)
        return {"sha256": _sha(data)}

    def _remote_sig(self, name):
        if self._remote_files is None:
            self._remote_files = self._target.record_files(*self._at)
        return self._remote_files.get(name)

    def _changed_elsewhere(self, name, data, base):
        sig = self._remote_sig(name)
        if sig is None or (base and base.get("etag") == sig[2]):
            return False
        return self._target.load_file(*self._at, name) != data

    def _merge_alerts(self):
        mine = load_sent(self._local, *self._at)
        theirs = load_sent(self._target, *self._at)
        merged = dict(theirs, **mine)
        if merged != theirs:
            save_sent(self._target, *self._at, merged)
        if merged != mine:
            save_sent(self._local, *self._at, merged)
        return self._local.load_file(*self._at, ALERTS_FILE)


def push_artifacts(local, target, app_name, verstr):
    """Upload the artifacts the remote lacks or holds at another size."""
    artifacts = local.list_artifacts(app_name, verstr)
    if not artifacts:
        return
    remote = {a["name"]: a["size"] for a in target.list_artifacts(app_name, verstr)}
    for artifact in artifacts:
        name = artifact["name"]
        if remote.get(name) != artifact["size"]:
            path = local.artifact_local_path(app_name, verstr, name)
            target.save_artifact_file(app_name, verstr, path, name=name)


def merge_fields(local, target, app_name, verstr, local_meta, remote_meta, base):
    """Three-way merge of :data:`MERGED_FIELDS`; returns ``(fields, warnings)``
    where *fields* is the new base. *base* is None without a ledger entry."""
    fields, warnings = {}, []
    for field in MERGED_FIELDS:
        mine, theirs = local_meta.get(field), remote_meta.get(field)
        fields[field] = _merged_value(field, mine, theirs, base, warnings)
    for storage, meta in ((target, remote_meta), (local, local_meta)):
        changed = {k: v for k, v in fields.items() if meta.get(k) != v}
        if changed:  # one (conditional) metadata rewrite per side
            storage.update_metadata(app_name, verstr, changed)
    return fields, warnings


def _merged_value(field, mine, theirs, base, warnings):
    if mine == theirs:
        return mine
    if base is not None and base.get(field) == theirs:
        return mine
    if base is not None and base.get(field) == mine:
        return theirs
    warnings.append(f"{field} differs on the remote ({theirs!r} vs local {mine!r}): "
                    "the remote value is kept")
    return theirs
