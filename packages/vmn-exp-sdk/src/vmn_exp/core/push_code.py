"""Code objects for ``vmn exp push``: uploaded only when the remote lacks them.

Code objects are content-addressed (:mod:`vmn_exp.core.code_store`), so the
remote may already hold an identical one from another host. A remote prune can
delete a just-uploaded object before the run that uses it is claimed, so the
pusher re-checks the marker after the claim (:meth:`CodePusher.recheck`).
"""
from vmn_exp.core.code_store import copy_code, stored_code

UPLOADED, PRESENT, MISSING = "uploaded", "present", "missing"


class CodePusher:
    """Pushes one app's code objects to *target*; share one across the runs of
    a push so each object costs one check. Counts ``uploaded``, ``present``
    and ``missing`` (not in the local root: pruned locally)."""

    def __init__(self, local, target, app_name):
        self._local = local
        self._target = target
        self._app_name = app_name
        self._done = {}
        self.uploaded = self.present = self.missing = 0

    def push(self, key):
        """:data:`UPLOADED`, :data:`PRESENT` or :data:`MISSING` for *key*."""
        if key not in self._done:
            if stored_code(self._target, self._app_name, key) is not None:
                self._done[key] = self._count(PRESENT)
            else:
                self._done[key] = self._upload(key)
        return self._done[key]

    def recheck(self, key):
        """After a claim: re-upload *key* if a remote prune removed it."""
        if stored_code(self._target, self._app_name, key) is None:
            self._done[key] = self._upload(key)

    def _upload(self, key):
        if not copy_code(self._local, self._target, self._app_name, key):
            return self._count(MISSING)
        return self._count(UPLOADED)

    def _count(self, status):
        setattr(self, status, getattr(self, status) + 1)
        return status
