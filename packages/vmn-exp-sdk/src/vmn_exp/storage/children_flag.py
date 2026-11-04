#!/usr/bin/env python3
"""An app's "every child has its marker" flag (:mod:`~vmn_exp.storage.child_markers`):
``.children_complete`` beside its records, a dot name no listing takes for a
record, holding ``complete <nonce>`` or ``dropped <nonce>``.

A pass over the app's runs (the first ``prune -v``, ``backfill-children``,
the UI's store upkeep) sets it; a child whose marker fails to write drops it.
The two race: a child created after the pass listed the app, whose marker
then failed, must not be covered by the pass's flag. So every write carries
a fresh nonce — every drop is a new version token (an S3 ETag, a local
file's content) — and a pass takes the token *before* it lists, then sets
the flag ``since`` it: an S3 ``If-Match``/``If-None-Match`` PUT, a local
compare-and-replace under the flag's lock file. A drop that landed in
between changed the token, so the pass's write is refused.

A cached store keeps the flag on its remote. A drop the remote refuses (it
is unreachable) is kept in the local copy instead; while it is there this
host trusts no flag, and its next read of the flag replays the drop on the
remote. Other hosts see the remote's stale flag until then — the same hosts
that cannot see this host's unpushed child either.
"""
import os
import uuid

from filelock import FileLock

from vmn_exp._base import VMN_LOGGER
from vmn_exp.storage.base import NO_FILE
from vmn_exp.storage.files import CHILDREN_COMPLETE_FILE, atomic_write
from vmn_exp.storage.s3_base import is_taken

_COMPLETE, _DROPPED = "complete", "dropped"


def _flag_text(complete):
    return f"{_COMPLETE if complete else _DROPPED} {uuid.uuid4().hex}\n"


class LocalChildrenFlag:
    has_child_markers = True

    def _children_flag_path(self, app_name):
        return os.path.join(self._snapshot_base_dir(app_name), CHILDREN_COMPLETE_FILE)

    def _children_flag_text(self, app_name):
        try:
            with open(self._children_flag_path(app_name), encoding="utf-8") as f:
                return f.read()
        except (FileNotFoundError, NotADirectoryError):
            return None

    def children_flag(self, app_name):
        text = self._children_flag_text(app_name)
        return NO_FILE if text is None else text

    def children_complete(self, app_name):
        return (self._children_flag_text(app_name) or "").startswith(_COMPLETE)

    def children_drop_kept(self, app_name):
        """Whether the flag is a drop (a cache's local copy: one its remote refused)."""
        return (self._children_flag_text(app_name) or "").startswith(_DROPPED)

    def set_children_complete(self, app_name, complete, since=None):
        return self._swap_children_flag(app_name, _flag_text(complete), since)

    def clear_children_flag(self, app_name, since=None):
        """Remove the flag while it holds *since*; whether it is gone."""
        return self._swap_children_flag(app_name, None, since)

    def _swap_children_flag(self, app_name, text, since):
        path = self._children_flag_path(app_name)
        if not os.path.isdir(os.path.dirname(path)):  # never an app of its own
            return since in (None, NO_FILE)
        with FileLock(path + ".lock"):
            if since is not None and self.children_flag(app_name) != since:
                return False
            if text is not None:
                atomic_write(path, text)
            elif os.path.exists(path):
                os.unlink(path)
        return True


class S3ChildrenFlag:
    has_child_markers = True

    def _children_complete_key(self, app_name):
        return f"{self._key_prefix(app_name)}/{CHILDREN_COMPLETE_FILE}"

    def children_flag(self, app_name):
        data, etag = self._get_with_etag(self._children_complete_key(app_name))
        return NO_FILE if data is None else etag

    def children_complete(self, app_name):
        data = self._get(self._children_complete_key(app_name)) or b""
        return data.startswith(_COMPLETE.encode())

    def set_children_complete(self, app_name, complete, since=None):
        condition = {} if since is None else (
            {"IfNoneMatch": "*"} if since == NO_FILE else {"IfMatch": since})
        try:
            self._put(self._children_complete_key(app_name), _flag_text(complete), **condition)
        except Exception as e:
            if since is not None and is_taken(e):
                return False
            raise
        return True


class CachedChildrenFlag:
    """The remote's flag (the local one without a remote), and in the local
    copy a drop the remote refused."""

    @property
    def _flag_holder(self):
        return self._remote or self._local

    @property
    def has_child_markers(self):
        return getattr(self._flag_holder, "has_child_markers", False)

    def children_flag(self, app_name):
        if not self._remote:
            return self._local.children_flag(app_name)
        return self._local.children_flag(app_name), self._remote.children_flag(app_name)

    def children_complete(self, app_name):
        if not self._remote:
            return self._local.children_complete(app_name)
        if self._local.children_drop_kept(app_name):
            self._replay_drop(app_name)
            return False
        return self._remote.children_complete(app_name)

    def set_children_complete(self, app_name, complete, since=None):
        if not self._remote:
            return self._local.set_children_complete(app_name, complete, since)
        if not complete:
            return self._drop(app_name)
        local_since, remote_since = since or (None, None)
        if not self._local.clear_children_flag(app_name, local_since):
            return False
        return self._remote.set_children_complete(app_name, True, since=remote_since)

    def _drop(self, app_name):
        try:
            return self._remote.set_children_complete(app_name, False)
        except Exception:
            VMN_LOGGER.debug(f"Dropping {app_name}'s child-marker flag on the remote "
                             "failed: kept locally", exc_info=True)
            return self._local.set_children_complete(app_name, False)

    def _replay_drop(self, app_name):
        kept = self._local.children_flag(app_name)
        try:
            self._remote.set_children_complete(app_name, False)
        except Exception:
            VMN_LOGGER.debug(f"Replaying {app_name}'s child-marker drop failed", exc_info=True)
            return
        self._local.clear_children_flag(app_name, kept)
