"""Whether a local-first cache's remote holds *this* record.

A record can exist locally only: it was recorded before a remote was
configured, or with a local dir alone. Its name was chosen without seeing the
remote, which may hold nothing under it — or a different run of the same
name. Either way, writing its files through would leave orphan objects (that
the next host to claim the name inherits) or overwrite the foreign record.

So a write goes through only to a record the remote is known to hold: one
this cache created, saved or pulled from the remote, or one whose remote
metadata names the same run (:func:`record_identity`). The answer is memoized per
cache: one metadata GET per record not created or pulled through it.
"""
from vmn_exp._base import VMN_LOGGER

# What makes two records the same run whatever their name or mutable fields.
_IDENTITY_FIELDS = ("timestamp", "base_commit", "diff_hash", "code_verstr")


def record_identity(metadata):
    """The fields of *metadata* that tell one run from another of the same name."""
    identity = tuple(metadata.get(field) for field in _IDENTITY_FIELDS)
    imported = metadata.get("imported_from")
    run_id = imported.get("run_id") if isinstance(imported, dict) else None
    return identity + (run_id,)


class RemotePresence:
    """``(app, verstr) -> bool`` memo of which records the remote holds."""

    def __init__(self, local, remote):
        self._local = local
        self._remote = remote
        self._known = {}

    def mark(self, app_name, verstr, held=True):
        self._known[(app_name, verstr)] = held

    def forget(self, app_name, verstr):
        self._known.pop((app_name, verstr), None)

    def holds(self, app_name, verstr):
        """Whether writes to *verstr* may go to the remote. Raises when the
        remote cannot be read (nothing is memoized then)."""
        key = (app_name, verstr)
        if key not in self._known:
            local = self._local.load_metadata(app_name, verstr)
            if local is None:
                return False
            self._known[key] = self._check(app_name, verstr, local)
        return self._known[key]

    def upload_if_missing(self, app_name, verstr):
        """Copy the local record to the remote unless the remote holds it."""
        if self.holds(app_name, verstr):
            return
        metadata, patches = self._local.load_record(app_name, verstr)
        if metadata is not None:
            self._remote.save(app_name, verstr, metadata, patches)
            self.mark(app_name, verstr)

    def _check(self, app_name, verstr, local):
        remote = self._remote.load_metadata(app_name, verstr)
        if remote is None:
            VMN_LOGGER.debug(f"{verstr} is local only: its writes stay local")
            return False
        if record_identity(local) != record_identity(remote):
            VMN_LOGGER.debug(
                f"The remote {verstr} is another run of that name: writes stay local"
            )
            return False
        return True

