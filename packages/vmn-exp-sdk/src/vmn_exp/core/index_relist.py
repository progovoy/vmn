#!/usr/bin/env python3
"""A journaled remote index's listings of every record, run behind serving.

A full listing of a remote store walks every object of every record: at 87k
runs on S3 that took the better part of an hour, one page after another, and
the refresh doing it held the index lock throughout, so no journal-announced
run was published until it ended. A :class:`Relisting` lists in a thread of
its own instead: the record names, then their files, ``LISTING_CHUNK``
records per listing and ``LISTING_WORKERS`` listings at a time. Each refresh
takes what is listed so far (:meth:`Relisting.take`) and applies it under
the lock like any other listing, so journal hints keep publishing in between.

Records that lie next to each other in the store's name order are listed in
one walk of their key range where the store can (``files_between``: about a
LIST per 1000 objects instead of three per record; at 497k S3 runs the
per-record listings took ~75 minutes). A cold index (nothing known) lists
the names a page at a time and each page's files as soon as the page
arrives, so its first records load while the rest are still being named;
:meth:`take` with a limit hands out the newest listed records first (by
their ``metadata.yml`` write time). An index that knows records lists the
names it does not know first, so the runs that appeared while it was down
show soonest.

A listing the store refuses (S3 ``SlowDown`` past botocore's retries) is
tried again, ``LISTING_ATTEMPTS`` times, the wait doubling from
``RETRY_SEC``; a chunk that keeps failing is handed over as keys to hint
(:meth:`Relisting.take_refused`), so one throttled chunk among hundreds never
ends the listing (it used to, and its successor started from the names).

A record a refresh listed itself after the relisting began (a hint, a live
re-listing: :meth:`Relisting.saw`) is left out of what it takes: that listing
is at least as fresh. A names-only relisting (after a journal overflow)
answers the names the index does not know, and the known ones the store no
longer lists, for the index to hint.
"""
import heapq
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from vmn_exp.core.index_listing import METADATA_FILE

LISTING_CHUNK = 250
LISTING_WORKERS = 8
# A refused listing (S3 SlowDown past botocore's retries) is tried this many
# times, RETRY_SEC doubling in between, before its records are left to hints.
LISTING_ATTEMPTS = 4
RETRY_SEC = 1.0
_LOGGER = logging.getLogger(__name__)
_wall = time.time


class _NoNames(RuntimeError):
    """The store cannot list record names (no retry helps)."""


def _retried(call, *args):
    """``call(*args)``, tried LISTING_ATTEMPTS times, waiting RETRY_SEC
    doubling in between."""
    for attempt in range(LISTING_ATTEMPTS):
        try:
            return call(*args)
        except _NoNames:
            raise
        except Exception:
            if attempt == LISTING_ATTEMPTS - 1:
                raise
            time.sleep(RETRY_SEC * 2 ** attempt)


def files_of(files, keys):
    """``files(keys)``, ``LISTING_CHUNK`` keys a call and ``LISTING_WORKERS``
    calls at a time (a burst of hints)."""
    keys = list(keys)
    if len(keys) <= LISTING_CHUNK:
        return files(keys)
    chunks = _chunks(keys)
    found = {}
    with ThreadPoolExecutor(max_workers=min(LISTING_WORKERS, len(chunks)),
                            thread_name_prefix="vmn-index-hints") as pool:
        for listing in pool.map(files, chunks):
            found.update(listing)
    return found


def _chunks(keys):
    return [keys[i : i + LISTING_CHUNK] for i in range(0, len(keys), LISTING_CHUNK)]


def _store_order(keys):
    """*keys* in the order a store lists record prefixes (``name/``)."""
    return sorted(keys, key=lambda key: f"{key}/")


def _written_at(files):
    sig = (files or {}).get(METADATA_FILE)
    return sig[1] if isinstance(sig, (list, tuple)) and len(sig) > 1 else 0


class Relisting:
    """One listing of an app's records, *files* or names alone, compared
    with the *known* keys; :meth:`take` hands it over a chunk at a time."""

    def __init__(self, watch, known, files=True):
        self.files = files
        self.started_at = _wall()
        self._watch, self._known = watch, frozenset(known)
        self._lock = threading.Lock()
        self._changed = threading.Condition(self._lock)  # notified as records are listed
        self._seen = set()
        self._ready = {}  # key -> its files ({} when it has none), listed, not taken yet
        self._newest = []  # heap of (-metadata write time, key) of the keys in _ready
        self._names = []  # a names-only relisting's keys, not taken yet
        self._refused = []  # keys whose listing kept failing, not taken yet
        self._total, self._listed, self._new, self._taken_new = None, 0, 0, 0
        self._done, self._error = False, None
        self._thread = threading.Thread(target=self._run, daemon=True, name="vmn-index-relist")
        self._thread.start()

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

    def new_names(self):
        """``(records known, names new to them listed so far, of those not
        taken yet)``; None while a cold listing named none yet."""
        with self._lock:
            if self._total is None and not self._known:
                return None
            return len(self._known), self._new, self._new - self._taken_new

    def ready(self):
        """Whether listed records wait to be taken."""
        with self._lock:
            return bool(self._ready or self._names)

    def wait_ready(self, timeout):
        """Until records wait to be taken or the listing ended, at most
        *timeout* seconds."""
        with self._changed:
            self._changed.wait_for(lambda: self._ready or self._names or self._done, timeout)

    def take(self, limit=None):
        """``(keys, {key: files}, done)`` of up to *limit* (None: all) listed
        records, the newest first (a names-only relisting: the keys to hint,
        no files); raises what failed the listing, once nothing listed is
        left to take."""
        with self._lock:
            if self._error is not None and not (self._ready or self._names):
                raise self._error
            if not self.files:
                keys, self._names = self._names, []
                return [k for k in keys if k not in self._seen], {}, self._done
            ready = self._ready
            if limit is None or len(ready) <= limit:
                keys, self._newest = list(ready), []
            else:
                keys = [heapq.heappop(self._newest)[1] for _ in range(limit)]
            files = {key: ready.pop(key) for key in keys}
            self._taken_new += sum(key not in self._known for key in keys)
            done, seen = self._done and not ready and self._error is None, set(self._seen)
        keys = [key for key in keys if key not in seen]
        return keys, {key: files[key] for key in keys if files[key]}, done

    def take_refused(self):
        """The keys whose listing kept failing since the last call, for the
        index to list as hints."""
        with self._lock:
            keys, self._refused = self._refused, []
        return keys

    def _run(self):
        try:
            if self.files and not self._known:
                self._stream_files()
                return
            names = _retried(self._record_names)
            unknown, gone = sorted(names - self._known), sorted(self._known - names)
            with self._lock:
                self._new = len(unknown)
            if not self.files:
                self._put(unknown + gone, {})
            else:
                self._list_files(unknown + gone, _store_order(names & self._known))
        except Exception as exc:  # handed to the next take()
            with self._lock:
                self._error = exc
        finally:
            with self._lock:
                self._done = True
                self._changed.notify_all()

    def _record_names(self):
        names = self._watch.record_names()
        if names is None:
            raise _NoNames("the store cannot list record names")
        return names

    def _stream_files(self):
        """Each page of names' files listed as soon as the page arrives; a
        names listing that fails starts over, past the names it listed."""
        with ThreadPoolExecutor(max_workers=LISTING_WORKERS,
                                thread_name_prefix="vmn-index-relist") as pool:
            futures = []
            _retried(self._list_pages, pool, set(), futures)
            for future in futures:
                future.result()
        with self._lock:
            self._total = self._total or 0

    def _list_pages(self, pool, named, futures):
        pages = self._watch.name_pages()
        if pages is None:
            raise _NoNames("the store cannot list record names")
        for page in pages:
            names = [name for name in page if name not in named]
            named.update(names)
            with self._lock:
                self._total = (self._total or 0) + len(names)
                self._new += len(names)
            futures += [pool.submit(self._list_chunk, self._watch.files_between, chunk)
                        for chunk in _chunks(names)]

    def _list_chunk(self, list_of, chunk):
        """``list_of(chunk)``, retried; past its attempts its keys are refused."""
        try:
            listing = _retried(list_of, chunk)
        except Exception as exc:
            _LOGGER.warning("Listing %d records failed (%s); they are listed again later",
                            len(chunk), exc)
            with self._lock:
                self._refused += chunk
                self._listed += len(chunk)
                self._changed.notify_all()
            return
        self._put(chunk, listing)

    def _list_files(self, keyed, between):
        """*keyed* listed record by record, then *between* (in store order)
        a walk of each chunk's range."""
        with self._lock:
            self._total = len(keyed) + len(between)
        jobs = [(self._watch.files, chunk) for chunk in _chunks(keyed)]
        jobs += [(self._watch.files_between, chunk) for chunk in _chunks(between)]
        with ThreadPoolExecutor(max_workers=max(1, min(LISTING_WORKERS, len(jobs))),
                                thread_name_prefix="vmn-index-relist") as pool:
            for future in [pool.submit(self._list_chunk, *job) for job in jobs]:
                future.result()

    def _put(self, keys, listing):
        with self._lock:
            if self.files:
                for key in keys:
                    files = self._ready[key] = listing.get(key) or {}
                    heapq.heappush(self._newest, (-_written_at(files), key))
            else:
                self._names += keys
            self._total = self._total if self._total is not None else len(keys)
            self._listed += len(keys)
            self._changed.notify_all()
