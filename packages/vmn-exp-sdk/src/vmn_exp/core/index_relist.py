#!/usr/bin/env python3
"""A journaled remote index's listings of every record, run behind serving.

A full listing of a remote store walks every object of every record: at 87k
runs on S3 that took the better part of an hour, one page after another, and
the refresh doing it held the index lock throughout, so no journal-announced
run was published until it ended. A :class:`Relisting` lists in a thread of
its own instead: the record names first (one call per 1000 records), then
their files, ``LISTING_CHUNK`` records per keyed listing and
``LISTING_WORKERS`` listings at a time — names the index does not know first,
so the runs that appeared while it was down show soonest. Each refresh takes
what is listed so far (:meth:`Relisting.take`) and applies it under the lock
like any other listing, so journal hints keep publishing in between.

A record a refresh listed itself after the relisting began (a hint, a live
re-listing: :meth:`Relisting.saw`) is left out of what it takes: that listing
is at least as fresh. A names-only relisting (after a journal overflow)
answers the names the index does not know, and the known ones the store no
longer lists, for the index to hint.
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

LISTING_CHUNK = 250
LISTING_WORKERS = 8
_wall = time.time


def files_of(files, keys):
    """``files(keys)``, ``LISTING_CHUNK`` keys a call and ``LISTING_WORKERS``
    calls at a time (a burst of hints)."""
    keys = list(keys)
    if len(keys) <= LISTING_CHUNK:
        return files(keys)
    chunks = [keys[i : i + LISTING_CHUNK] for i in range(0, len(keys), LISTING_CHUNK)]
    found = {}
    with ThreadPoolExecutor(max_workers=min(LISTING_WORKERS, len(chunks)),
                            thread_name_prefix="vmn-index-hints") as pool:
        for listing in pool.map(files, chunks):
            found.update(listing)
    return found


class Relisting:
    """One listing of an app's records, *files* or names alone, compared
    with the *known* keys; :meth:`take` hands it over a chunk at a time."""

    def __init__(self, watch, known, files=True):
        self.files = files
        self.started_at = _wall()
        self._watch, self._known = watch, frozenset(known)
        self._lock = threading.Lock()
        self._seen = set()
        self._ready = []  # [(keys, {key: files})] listed, not taken yet
        self._total, self._listed = None, 0
        self._done, self._error = False, None
        self._thread = threading.Thread(target=self._run, daemon=True, name="vmn-index-relist")
        self._thread.start()

    def wait(self):
        """Until everything is listed (a cold index has nothing to serve meanwhile)."""
        self._thread.join()

    def saw(self, keys):
        """A refresh listed *keys* itself: leave them out of what it takes."""
        with self._lock:
            self._seen.update(keys)

    def progress(self):
        """The share of the records listed so far; None before the names are."""
        with self._lock:
            if self._total is None:
                return None
            return self._listed / self._total if self._total else 1.0

    def take(self, limit=None):
        """``(keys, {key: files}, done)`` of up to about *limit* (None: all)
        listed records (a names-only relisting: the keys to hint, no files);
        raises what failed the listing."""
        with self._lock:
            if self._error is not None:
                raise self._error
            keys, files = [], {}
            while self._ready and (limit is None or len(keys) < limit):
                chunk, listing = self._ready.pop(0)
                keys += chunk
                files.update(listing)
            done, seen = self._done and not self._ready, set(self._seen)
        keys = [key for key in keys if key not in seen]
        return keys, {key: files[key] for key in keys if key in files}, done

    def _run(self):
        try:
            names = self._watch.record_names()
            if names is None:
                raise RuntimeError("the store cannot list record names")
            unknown, gone = sorted(names - self._known), sorted(self._known - names)
            if not self.files:
                self._put(unknown + gone, {}, len(unknown) + len(gone))
            else:
                self._list_files(unknown + gone + sorted(names & self._known))
        except Exception as exc:  # handed to the next take()
            with self._lock:
                self._error = exc
        finally:
            with self._lock:
                self._done = True

    def _list_files(self, keys):
        with self._lock:
            self._total = len(keys)
        chunks = [keys[i : i + LISTING_CHUNK] for i in range(0, len(keys), LISTING_CHUNK)]
        with ThreadPoolExecutor(max_workers=max(1, min(LISTING_WORKERS, len(chunks))),
                                thread_name_prefix="vmn-index-relist") as pool:
            futures = {pool.submit(self._watch.files, chunk): chunk for chunk in chunks}
            for future in as_completed(futures):
                self._put(futures[future], future.result(), len(futures[future]))

    def _put(self, keys, listing, count):
        with self._lock:
            self._ready.append((keys, listing))
            self._total = self._total if self._total is not None else count
            self._listed += count
