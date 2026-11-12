#!/usr/bin/env python3
"""How :class:`~vmn_exp.core.index.ExperimentIndex` reads the records a
refresh hands it: in worker processes for a cold local build, concurrently
for a remote backend, else one by one (a mixin; all state stays on the
index). Each record goes through the index's ``_refresh_one``, which stays
in core/index.py because tests patch what it reads there."""
from vmn_exp.core.index_remote_workers import RemoteLoaders, worker_count
from vmn_exp.core.index_workers import load_new_records


class IndexRead:
    def _refresh_local(self, work):
        direct_files = getattr(self._storage, "direct_files", None)
        return self._refresh_records(work, direct_files() if direct_files else self._storage)

    def _refresh_records(self, work, direct):
        """``(key, record, dirty, moved, state moved)`` per ``(key, names,
        record)`` in *work*.

        A cold build's many new local records load in worker processes; a
        remote backend's records are re-read concurrently: each costs a few
        round trips, and a cold index on S3 would otherwise pay them serially.
        """
        done = load_new_records(self._storage, direct, self.app_name, work)
        if not done and self._backlog():
            done = self._remote_loaders().load(self.app_name, work, self._unreadable)
        todo = [w for w in work if w[0] not in done]
        done.update(zip((w[0] for w in todo), self._refresh_all(todo, direct)))
        return [(key, *done[key]) for key, _, _ in work]

    def _remote_loaders(self):
        """The worker processes a bulk load of a remote backend reads its new
        records in (:mod:`~vmn_exp.core.index_remote_workers`): started once,
        none when the backend cannot be opened again elsewhere."""
        if self._loaders is None:
            spec_of = getattr(self._storage, "worker_spec", None)
            spec = spec_of() if spec_of and self._remote() else None
            self._loaders = RemoteLoaders(spec, worker_count() if spec else 0)
        return self._loaders

    def _close_loaders(self):
        loaders, self._loaders = self._loaders, None
        if loaders is not None:
            loaders.close()

    def _refresh_all(self, work, direct):
        if len(work) > 1 and self._remote():
            # A warm start's lazy records read their stored head here, in
            # order (a chunk per query), never from the pool's threads.
            for _, _, record in work:
                if record is not None:
                    record.get("meta_sig")
            try:
                return self._pool.map(lambda w: self._refresh_one(*w, direct), work)
            finally:
                if not self._unread and not self._backlog():  # else the next chunk reuses it
                    self._pool.close()
        return [self._refresh_one(*w, direct) for w in work]

    def _remote(self):
        is_remote = getattr(self._storage, "is_remote", None)
        return bool(is_remote and is_remote())
