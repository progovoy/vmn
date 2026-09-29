"""Push one local run to a remote store under the same name (``vmn exp push``).

Steps, each resumable (a failed push is simply run again):

1. the code object, unless the remote already holds it;
2. claim the name with the run identity as claim token (a crashed claim of
   ours resumes), or match an existing remote record by identity; then
   re-check the code object (a remote prune may have raced step 1);
3. the other top-level files by sha (:mod:`vmn_exp.core.push_files`);
4. the logs per writer from the remote offset (:mod:`vmn_exp.core.push_logs`);
5. artifacts missing remotely or of another size;
6. the three-way merge of ``archived``/``note``;
7. a final LIST for the ETags, then the ledger entry.

A remote record (or claim) of the same name that is another run is a
:data:`COLLISION`: nothing is written into it. Renaming is up to the caller.
Selection, ordering, the status gate and locking are the caller's too.
"""
import inspect
from dataclasses import dataclass, field

from vmn_exp._base import now_iso
from vmn_exp.core.push_code import MISSING, CodePusher
from vmn_exp.core.push_files import merge_fields, push_artifacts, push_files
from vmn_exp.core.push_identity import record_fingerprint, run_identity
from vmn_exp.core.push_ledger import PushLedger
from vmn_exp.core.push_logs import push_logs
from vmn_exp.core.status import run_finished

NEW, UPDATE, UP_TO_DATE, COLLISION, FAILED = (
    "new", "update", "up-to-date", "collision", "failed",
)
_REQUIRED = ("put_log_segment", "log_objects", "list_artifacts", "record_files",
             "compact_log_segments")


class _Collision(Exception):
    """The remote name belongs to another run."""


@dataclass
class Outcome:
    """What pushing *verstr* did: ``status`` is one of :data:`NEW`,
    :data:`UPDATE`, :data:`UP_TO_DATE`, :data:`COLLISION`, :data:`FAILED`;
    ``detail`` explains a collision or failure."""

    verstr: str
    status: str
    detail: str = ""
    warnings: list = field(default_factory=list)


def require_push_target(target):
    """ValueError unless *target* is a remote store push can write safely:
    conditional log segments, record listings and a claim token."""
    if not target.is_remote():
        raise ValueError(
            "A push target must be a remote store (s3://, gs://, az://); a "
            "file:// store is a directory: rsync the experiments dir instead"
        )
    missing = [name for name in _REQUIRED if not hasattr(target, name)]
    params = inspect.signature(target.create_exclusive).parameters
    if missing or "claim_token" not in params:
        raise ValueError(f"The store {type(target).__name__} cannot be pushed to")


def push_run(local, target, app_name, verstr, ledger=None, code=None):
    """Push local run *verstr* of *app_name* from *local* (a
    ``LocalSnapshotStorage``) to *target* under the same name; returns an
    :class:`Outcome`. Pass one *ledger* (:class:`PushLedger`) and one *code*
    (:class:`CodePusher`) for every run of a push; both default per call."""
    ledger = ledger or PushLedger.for_target(local, app_name, target)
    code = code or CodePusher(local, target, app_name)
    meta = local.load_metadata(app_name, verstr)
    if meta is None:
        return Outcome(verstr, FAILED, "no such local run")
    identity = run_identity(app_name, meta)
    entry = ledger.get(verstr) or {}
    if entry.get("identity") != identity:
        entry = {}
    if entry.get("complete") and entry.get("fingerprint") == record_fingerprint(
        local, app_name, verstr
    ):
        return Outcome(verstr, UP_TO_DATE)
    job = _RunPush(local, target, app_name, verstr, code, meta, identity, entry)
    try:
        outcome = job.run()
    except Exception as e:
        outcome = Outcome(verstr, FAILED, str(e) or type(e).__name__, job.warnings)
    if job.claimed:
        ledger.put(verstr, job.entry)
    return outcome


class _RunPush:
    def __init__(self, local, target, app_name, verstr, code, meta, identity, entry):
        self._local, self._target, self._code = local, target, code
        self._app, self._verstr = app_name, verstr
        self._meta, self._identity = meta, identity
        self._base = entry
        self.entry = dict(entry, identity=identity, remote_verstr=verstr,
                          complete=False)
        self.claimed = False
        self.warnings = []

    def run(self):
        key = self._meta.get("code")
        if key and not self._base.get("code_pushed"):
            self._push_code(key)
        try:
            status, remote_meta = self._claim()
        except _Collision as e:
            return Outcome(self._verstr, COLLISION, str(e), self.warnings)
        if key and status == NEW and self.entry.get("code_pushed"):
            self._code.recheck(key)
        self._push_contents(remote_meta)
        return Outcome(self._verstr, status, warnings=self.warnings)

    def _push_code(self, key):
        pushed = self._code.push(key) != MISSING
        if not pushed:
            self.warnings.append(f"code missing locally: {key}")
        self.entry.update(code_key=key, code_pushed=pushed)

    def _claim(self):
        """``(NEW | UPDATE, remote metadata)``; raises :class:`_Collision`."""
        remote_meta = self._target.load_metadata(self._app, self._verstr)
        if remote_meta is None:
            _, patches = self._local.load_record(self._app, self._verstr)
            if not self._target.create_exclusive(
                self._app, self._verstr, self._meta, patches or {},
                claim_token=self._identity,
            ):
                raise _Collision("the remote name is claimed by another run")
            self.claimed = True
            return NEW, self._meta
        if run_identity(self._app, remote_meta) != self._identity:
            raise _Collision("the remote holds another run of that name")
        self.claimed = True
        return UPDATE, remote_meta

    def _push_contents(self, remote_meta):
        at = (self._local, self._target, self._app, self._verstr)
        files, warnings = push_files(*at, self._base.get("files"))
        self.entry["files"] = files
        self.warnings += warnings
        self.entry["log_bytes"] = push_logs(
            *at, self._base.get("log_bytes"),
            finished=run_finished(self._local, self._app, self._verstr),
        )
        push_artifacts(*at)
        fields, warnings = merge_fields(
            *at, self._meta, remote_meta, self._base.get("fields")
        )
        self.entry["fields"] = fields
        self.warnings += warnings
        self._fill_etags()
        self.entry.update(
            fingerprint=record_fingerprint(self._local, self._app, self._verstr),
            complete=True,
            pushed_at=now_iso(),
        )

    def _fill_etags(self):
        fresh = [r for r in self.entry["files"].items() if "etag" not in r[1]]
        if not fresh:
            return
        listing = self._target.record_files(self._app, self._verstr)
        for name, record in fresh:
            record["etag"] = (listing.get(name) or (None, None, None))[2]
