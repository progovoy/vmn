#!/usr/bin/env python3
"""Child markers: an empty ``children/<child verstr>`` object in a parent's
record names one of its children, so an outer run's children are one listing
of its own record away — not the ``parent`` field of every record in the app.

The markers are an accelerator, never the source of truth: a child's
``parent`` field is. They are written best-effort when a child is created
(:func:`vmn_exp.core.children.mark_parent`), dropped when it is pruned, and
``vmn-exp backfill-children`` writes the ones a store lacks. A marker may
outlive its child or name a run that was renamed: readers skip a marker whose
record does not exist.

Not part of a record's files, by design: ``children/`` is neither a signed
folder of a local listing (:mod:`~vmn_exp.storage.listing`) nor one of the
S3 listing's record folders (:mod:`~vmn_exp.storage.s3_listing` skips the
subtree), so adding a child never makes its parent's record look changed to
an index. Locally only the first marker moves the record directory's mtime
(creating ``children/``); later ones touch ``children/`` alone. Nor are they
journaled: the child's own claim is, and the index derives the edge from it.
"""
import os

from vmn_exp.storage.files import CHILDREN_DIR, safe_verstr, unsafe_verstr


def _marker_names(names):
    return sorted(unsafe_verstr(n) for n in names if n and not n.startswith("."))


class LocalChildren:
    def _children_dir(self, app_name, parent):
        return os.path.join(self._snapshot_dir(app_name, parent), CHILDREN_DIR)

    def mark_child(self, app_name, parent, child):
        """Write *parent*'s marker of *child*; False when *parent* is no record."""
        if self._refuse_orphan_write(app_name, parent, "a child marker"):
            return False
        folder = self._children_dir(app_name, parent)
        try:
            os.mkdir(folder)  # never the record itself: a deleted one stays deleted
        except FileExistsError:
            pass
        path = os.path.join(folder, safe_verstr(child))
        os.close(os.open(path, os.O_WRONLY | os.O_CREAT, 0o666))
        return True

    def unmark_child(self, app_name, parent, child):
        try:
            os.unlink(os.path.join(self._children_dir(app_name, parent), safe_verstr(child)))
        except FileNotFoundError:
            pass

    def list_children(self, app_name, parent):
        """The verstrs *parent*'s markers name — one directory listing."""
        try:
            return _marker_names(os.listdir(self._children_dir(app_name, parent)))
        except (FileNotFoundError, NotADirectoryError):
            return []


class S3Children:
    def _children_prefix(self, app_name, parent):
        return f"{self._record_prefix(app_name, parent)}/{CHILDREN_DIR}/"

    def mark_child(self, app_name, parent, child):
        self._put(self._children_prefix(app_name, parent) + safe_verstr(child), b"")
        return True

    def unmark_child(self, app_name, parent, child):
        key = self._children_prefix(app_name, parent) + safe_verstr(child)
        self._s3.delete_object(Bucket=self.bucket, Key=key)

    def list_children(self, app_name, parent):
        """The verstrs *parent*'s markers name — one LIST per 1000 children."""
        prefix = self._children_prefix(app_name, parent)
        names = (o["Key"][len(prefix):] for o in self._objects(prefix))
        return _marker_names(n for n in names if "/" not in n)


class CachedChildren:
    """Both copies: the local one when it is a replica, the remote one when
    it holds the parent."""

    def mark_child(self, app_name, parent, child):
        marked = False
        if self._local_is_replica:
            marked = self._local.mark_child(app_name, parent, child)
        if self._remote and self._remote_holds(app_name, parent):
            marked = self._remote.mark_child(app_name, parent, child) or marked
        return marked

    def _remote_holds(self, app_name, parent):
        if self._local.exists(app_name, parent):
            return self._presence.holds(app_name, parent)
        return self._remote.exists(app_name, parent)

    def unmark_child(self, app_name, parent, child):
        self._local.unmark_child(app_name, parent, child)
        if self._remote:
            self._remote.unmark_child(app_name, parent, child)

    def list_children(self, app_name, parent):
        found = set(self._local.list_children(app_name, parent)) if self._local_is_replica else set()
        found.update(self._remote_listing([], "list_children", app_name, parent))
        return sorted(found)
