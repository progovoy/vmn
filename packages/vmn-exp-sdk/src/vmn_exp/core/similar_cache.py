#!/usr/bin/env python3
"""Similar indexes (:mod:`vmn_exp.core.similar_index`), each built once.

:func:`index_for` keeps a snapshot's index while the snapshot lives and
builds it single-flight: concurrent callers on one snapshot wait for one
build, run on the first caller's thread under its deadline. A builder that
stops at its deadline caches nothing and leaves the build to a waiter. A
structured request on a snapshot holding a words-only index completes it
from that index's profiles.

:class:`IndexLineages` serves a long-lived process (the UI) whose snapshots
come in lineages — the successive generations of one app's index. A lineage
builds one index at a time, on a daemon thread without a deadline, from its
last index (:func:`~vmn_exp.core.similar_index.build_index`): a heartbeat's
generation gets that index itself, another costs what changed. A caller
past its deadline raises :class:`SimilarDeadlineExceeded` while the build
goes on, so a later request finds it; a build that fails raises its error in
the callers waiting for it. Once a lineage filed structured tokens it keeps
them current, for text searches too: patching them costs little, filing
them anew a whole pass.
"""
import logging
import threading
import weakref
from collections import OrderedDict

from vmn_exp.core import similar_index
from vmn_exp.core.similar_index import SimilarDeadlineExceeded, build_index

LINEAGES_KEPT = 256
_LOGGER = logging.getLogger(__name__)
_CACHE = weakref.WeakKeyDictionary()  # snapshot -> _Slot
_LOCK = threading.Lock()  # guards _CACHE and every _Slot


class _Build:
    """A build in flight: *done* once it ended, *error* when it failed in the background."""

    def __init__(self):
        self.done, self.error = threading.Event(), None


class _Slot:
    """A snapshot's best index so far, and its build in flight."""

    def __init__(self):
        self.index, self.build = None, None


def _slot(snapshot):
    """*snapshot*'s slot."""
    with _LOCK:
        slot = _CACHE.get(snapshot)
        if slot is None:
            slot = _CACHE[snapshot] = _Slot()
        return slot


def _wait(build, deadline):
    if deadline is None:
        return build.done.wait()
    remaining = deadline - similar_index._clock()
    return remaining > 0 and build.done.wait(remaining)


def _run(slot, build, make, deadline, own, background=False):
    try:
        index = make(deadline, own)
    except Exception as e:
        if background:
            build.error = e  # before *done* is set: a woken waiter reads it
        raise
    else:
        with _LOCK:
            slot.index = index
    finally:
        with _LOCK:
            slot.build = None
        build.done.set()


def _run_in_background(slot, build, make, own):
    try:
        _run(slot, build, make, None, own, background=True)
    except Exception:
        _LOGGER.warning("Building a similar-runs index failed", exc_info=True)


def _claim(slot, structured):
    """``(index, build, mine)`` of *slot*, under ``_LOCK``: no *build* when its
    index will do, else the build in flight — *mine* when this caller just
    claimed it — and the slot's index so far."""
    index = slot.index
    if index is not None and (index.structured or not structured):
        return index, None, False
    if slot.build is not None:
        return index, slot.build, False
    slot.build = _Build()
    return index, slot.build, True


def _start_in_background(slot, build, make, own):
    threading.Thread(target=_run_in_background, args=(slot, build, make, own),
                     name="vmn-similar-index", daemon=True).start()


def _obtain(slot, structured, deadline, make, background=False):
    """*slot*'s index (with structured tokens when *structured*), built by
    *make(deadline, own)* — *own* the slot's words-only index or None — by
    one caller at a time: on the caller's thread, or with *background* on a
    thread of its own."""
    while True:
        with _LOCK:
            index, build, mine = _claim(slot, structured)
        if build is None:
            return index
        if mine and not background:
            _run(slot, build, make, deadline, index)
            continue
        if mine:
            _start_in_background(slot, build, make, index)
        if not _wait(build, deadline):
            raise SimilarDeadlineExceeded
        if build.error is not None:
            raise build.error


def index_for(snapshot, deadline=None, structured=True):
    """The :class:`~vmn_exp.core.similar_index.SimilarIndex` of *snapshot*
    (see the module docstring); *structured* False settles for words only."""
    return _obtain(_slot(snapshot), structured, deadline,
                   lambda by, own: build_index(snapshot, by, own, structured))


class _Lineage:
    def __init__(self):
        self.lock, self.index = threading.Lock(), None


class IndexLineages:
    """The last index of each lineage of snapshots (at most
    :data:`LINEAGES_KEPT`, the least recently used dropped), and their
    builds; see the module docstring."""

    def __init__(self):
        self._lock, self._lineages = threading.Lock(), OrderedDict()

    def index_for(self, key, snapshot, deadline=None, structured=True):
        """*snapshot*'s index, built in lineage *key*; raises
        :class:`SimilarDeadlineExceeded` when it is not ready by *deadline*."""
        return _obtain(_slot(snapshot), structured, deadline,
                       self._maker(key, snapshot, structured), background=True)

    def start(self, key, snapshot, structured=True):
        """Start building *snapshot*'s index in lineage *key*, unless it is
        built or being built; :meth:`index_for` then waits for it."""
        slot = _slot(snapshot)
        with _LOCK:
            own, build, mine = _claim(slot, structured)
        if mine:
            _start_in_background(slot, build, self._maker(key, snapshot, structured), own)

    def _maker(self, key, snapshot, structured):
        return lambda _by, own: self._build(key, snapshot, own, structured)

    def _build(self, key, snapshot, own, structured):
        lineage = self._lineage(key)
        with lineage.lock:
            previous = lineage.index or own
            structured = structured or bool(previous and previous.structured)
            lineage.index = build_index(snapshot, None, previous, structured)
            return lineage.index

    def _lineage(self, key):
        with self._lock:
            lineage = self._lineages.pop(key, None) or _Lineage()
            self._lineages[key] = lineage
            while len(self._lineages) > LINEAGES_KEPT:
                self._lineages.popitem(last=False)
            return lineage
